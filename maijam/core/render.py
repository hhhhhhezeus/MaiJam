"""Local procedural synthesis and standard MIDI export; no samples or ML services."""
from __future__ import annotations

from array import array
import math
from pathlib import Path
import random
import struct
import sys
import wave

RATE = 22050
TAU = 2 * math.pi


def envelope(t, length, attack=.012, decay=.06, sustain=.68, release=.10):
    if t < attack: return t / attack
    if t < attack + decay: return 1 - (1 - sustain) * (t - attack) / decay
    return sustain * min(1.0, max(0.0, (length - t) / release))


def render_wav(score, path, sample_rate=RATE, max_seconds=65):
    """Render to mono PCM WAV. Each note is synthesized offline, mixed, then peak-limited."""
    bpm = score['bpm']
    seconds = score['bars'] * 240 / bpm
    if not (0 < seconds <= max_seconds):
        raise ValueError('recording duration outside allowed range')
    count = int(seconds * sample_rate)
    mix = array('f', [0.0]) * count
    samples_per_tick = sample_rate * 60 / bpm / 4
    for i, note in enumerate(score['notes']):
        start = int(note['start'] * samples_per_tick)
        length = min(int(note['duration'] * samples_per_tick), count - start)
        if length <= 0: continue
        velocity = note['velocity'] / 127
        track = note['track']
        wave_type = note['wave']
        freq = 440 * 2 ** ((note['pitch'] - 69) / 12)
        # Repeatable per-note noise (kick is pitched, snare/hat are noise).
        rng = random.Random(score['seed'] * 65537 + i)
        duration = length / sample_rate
        gain = {'drums': .17, 'bass': .17, 'chords': .065, 'lead': .11, 'arp': .06, 'fx': .06}.get(track, .05) * velocity
        phase = 0.0
        for n in range(length):
            t = n / sample_rate
            if wave_type == 'kick':
                phase += TAU * (45 + 110 * math.exp(-t * 28)) / sample_rate
                value = math.sin(phase) * math.exp(-t * 15)
            elif wave_type in ('snare', 'hat'):
                decay = 32 if wave_type == 'snare' else 85
                value = (rng.random() * 2 - 1) * math.exp(-t * decay)
            else:
                phase += freq / sample_rate
                x = phase % 1.0
                if wave_type == 'square': value = .72 if x < .5 else -.72
                elif wave_type == 'saw': value = 2 * x - 1
                elif wave_type == 'triangle': value = 1 - 4 * abs(x - .5)
                else: value = math.sin(TAU * x)
                value *= envelope(t, duration)
            mix[start + n] += gain * value
    peak = max((abs(x) for x in mix), default=0.0)
    # Never amplify; a single consistent gain prevents integer clipping.
    gain = min(1.0, .94 / peak) if peak else 1.0
    pcm = array('h', (int(max(-32767, min(32767, sample * gain * 32767))) for sample in mix))
    if sys.byteorder != 'little': pcm.byteswap()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(sample_rate); out.writeframes(pcm.tobytes())
    return {'seconds': count / sample_rate, 'sample_rate': sample_rate, 'peak': min(.94, peak * gain), 'bytes': path.stat().st_size}


def variable(value):
    if value < 0: raise ValueError('negative MIDI delta')
    buf = [value & 0x7f]
    value >>= 7
    while value:
        buf.insert(0, (value & 0x7f) | 0x80)
        value >>= 7
    return bytes(buf)


def render_midi(score, path):
    ticks_per_beat = 480
    events = []
    channels = {'drums': 9, 'bass': 0, 'chords': 1, 'lead': 2, 'arp': 3, 'fx': 4}
    instruments = {'bass': 38, 'chords': 89, 'lead': 81, 'arp': 80, 'fx': 98}
    tempo = int(60_000_000 / score['bpm'])
    events.append((0, 0, b'\xff\x51\x03' + tempo.to_bytes(3, 'big')))
    events.append((0, 0, b'\xff\x58\x04\x04\x02\x18\x08'))
    for track, program in instruments.items():
        events.append((0, 0, bytes((0xc0 | channels[track], program))))
    for n in score['notes']:
        ch = channels[n['track']]
        start = n['start'] * (ticks_per_beat // 4)
        end = (n['start'] + n['duration']) * (ticks_per_beat // 4)
        events.append((start, 2, bytes((0x90 | ch, n['pitch'], n['velocity']))))
        events.append((end, 1, bytes((0x80 | ch, n['pitch'], 0))))
    events.sort(key=lambda x: (x[0], x[1], x[2]))
    data = bytearray(); previous = 0
    for tick, _, message in events:
        data.extend(variable(tick - previous)); data.extend(message); previous = tick
    data.extend(b'\x00\xff\x2f\x00')
    Path(path).write_bytes(b'MThd' + struct.pack('>IHHH', 6, 0, 1, ticks_per_beat) + b'MTrk' + struct.pack('>I', len(data)) + data)
    return {'bytes': Path(path).stat().st_size, 'notes': len(score['notes'])}
