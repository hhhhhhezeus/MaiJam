"""Deterministic, bar-quantized arrangement using an original procedural score."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import random

STYLES = {
    'lofi': {'bpm': 76, 'progression': (0, 5, 3, 4), 'drums': (0, 8), 'hat': 4, 'wave': 'sine', 'key': 57},
    'synthwave': {'bpm': 104, 'progression': (0, 5, 3, 4), 'drums': (0, 8), 'hat': 2, 'wave': 'saw', 'key': 57},
    'chiptune': {'bpm': 138, 'progression': (0, 3, 4, 0), 'drums': (0, 8), 'hat': 4, 'wave': 'square', 'key': 60},
    'house': {'bpm': 122, 'progression': (0, 5, 3, 4), 'drums': (0, 4, 8, 12), 'hat': 2, 'wave': 'triangle', 'key': 57},
}
SCALE = (0, 2, 3, 5, 7, 8, 10)  # natural minor; relative major is used for bright accents
TRACKS = ('drums', 'bass', 'chords', 'lead', 'arp', 'fx')


@dataclass(frozen=True)
class Note:
    start: int        # sixteenth-note ticks, four beats per bar
    duration: int
    pitch: int        # MIDI pitch, drum pitch uses General MIDI assignments
    velocity: int
    track: str
    wave: str

    def as_dict(self):
        return asdict(self)


def clamp(x, low, high):
    return max(low, min(high, x))


def scale_pitch(root: int, degree: int) -> int:
    octave, index = divmod(degree, 7)
    return root + octave * 12 + SCALE[index]


def compose(style: str, seed: int, bars: int, controls=None, bpm=None, root=None, mute=None, levels=None):
    """Generate note events; controls are per-bar summaries, never raw message text."""
    if style not in STYLES or not 1 <= bars <= 256:
        raise ValueError('unknown style or bar count outside 1..256')
    spec = STYLES[style]
    bpm = int(bpm or spec['bpm'])
    root = int(root if root is not None else spec['key'])
    if not 40 <= bpm <= 200 or not 36 <= root <= 72:
        raise ValueError('BPM or root outside supported range')
    mute = set(mute or ())
    levels = levels or {}
    controls = controls or []
    rng = random.Random(int(seed))
    motif = [rng.choice((0, 2, 4, 7)), rng.choice((2, 3, 4)), rng.choice((0, 2, 5)), rng.choice((0, 2, 4))]
    notes = []
    role_factors = {}

    def add(tick, dur, pitch, velocity, track, wave=None):
        if track in mute:
            return
        level = clamp(float(levels.get(track, 1.0)), 0.0, 1.5)
        vel = int(clamp(round(velocity * level * role_factors.get(track, 1.0)), 0, 127))
        if vel:
            notes.append(Note(tick, dur, int(clamp(pitch, 0, 127)), vel, track, wave or spec['wave']))

    for bar in range(bars):
        control = controls[bar] if bar < len(controls) else {}
        energy = clamp(float(control.get('energy', .35)), 0, 1)
        accent = clamp(float(control.get('accent', 0)), 0, 1)
        fill = clamp(float(control.get('fill', 0)), 0, 1)
        brightness = clamp(float(control.get('brightness', 0)), -1, 1)
        layers = int(clamp(int(control.get('layers', 4)), 1, 6))
        role_factors = {track: min(1.15, 1.0 + .03 * int(count)) for track, count in control.get('roles', {}).items() if track in TRACKS}
        base = bar * 16
        degree = spec['progression'][bar % 4]
        chord = [scale_pitch(root, degree + d) for d in (0, 2, 4)]
        if brightness > .45:
            chord[1] += 1
        # Every style maintains its characteristic kick and snare pattern.
        for step in spec['drums']:
            add(base + step, 1, 36, 80 + 20 * energy + (12 * accent if step == 0 else 0), 'drums', 'kick')
        for step in (4, 12):
            add(base + step, 1, 38, 65 + 22 * energy, 'drums', 'snare')
        if layers >= 2:
            for step in range(2, 16, spec['hat']):
                add(base + step, 1, 42, 36 + 28 * energy, 'drums', 'hat')
        if fill > .15:
            for step in (13, 14, 15):
                add(base + step, 1, 38, 45 + 25 * fill, 'drums', 'snare')
        # Root + fifth provide coherent bass against the current triad.
        bass_steps = (0, 4, 8, 12) if style == 'house' else (0, 8)
        if layers >= 2:
            for j, step in enumerate(bass_steps):
                add(base + step, 3 if style == 'house' else 6, chord[0] - 12 + (7 if j % 2 else 0), 73 + 12 * energy, 'bass', 'triangle')
        if layers >= 3:
            for pitch in chord:
                add(base, 14, pitch, 46 + 10 * energy, 'chords', 'sine' if style == 'lofi' else spec['wave'])
        if layers >= 4:
            # Four-bar phrase shares motif; bar four resolves to chord root.
            for j, step in enumerate((0, 4, 8, 12)):
                d = motif[(j + (bar % 2)) % 4]
                if bar % 4 == 3 and j == 3:
                    pitch = chord[0] + 12
                else:
                    pitch = scale_pitch(root + 12, degree + d % 5)
                if (j == 2 and bar % 2 and energy < .5):
                    continue
                add(base + step, 3, pitch, 65 + 20 * energy + (10 * accent if step == 0 else 0), 'lead')
        if layers >= 5 or style == 'synthwave':
            for j, step in enumerate(range(0, 16, 2)):
                add(base + step, 1, chord[j % 3] + 12, 40 + 15 * energy, 'arp', spec['wave'])
        if layers >= 6 and accent > .2:
            add(base, 4, chord[2] + 12, 35 + 15 * accent, 'fx', 'sine')
    return {'style': style, 'bpm': bpm, 'root': root, 'bars': bars, 'seed': int(seed), 'notes': [x.as_dict() for x in sorted(notes, key=lambda n: (n.start, n.track, n.pitch))]}
