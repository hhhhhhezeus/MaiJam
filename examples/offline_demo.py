"""Simulate five players, aggregate at bar boundaries, export original WAV/MIDI."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maijam.core.events import EventMapper
from maijam.core.music import compose
from maijam.core.render import render_wav, render_midi


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'demo')
    parser.add_argument('--style', choices=['lofi', 'synthwave', 'chiptune', 'house'], default='lofi')
    parser.add_argument('--seed', type=int, default=20261029)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # Inputs are ephemeral: the generated JSON contains aggregate features only.
    sources = [
        (1,'u1','哈哈哈哈','drums'), (3,'u2','很好听！','bass'),
        (5,'u3','✨🎵😀','lead'), (7,'u4','这个节奏让我想起夏天','chords'),
        (9,'u5','🎉🎉','arp'), (13,'u1','哈哈哈','drums'),
        (18,'u3','！！！！','lead'), (22,'u2','好有意思','bass'),
        (29,'u5','🎶😊','arp'), (35,'u4','慢慢来','chords'),
        (44,'u3','✨','lead'), (52,'u1','哈哈哈哈','drums')]
    bpm = {'lofi': 76, 'synthwave': 104, 'chiptune': 138, 'house': 122}[args.style]
    bars = int(60 * bpm // 240)
    mapper, controls, cursor = EventMapper(), [], 0
    for bar in range(bars):
        boundary = (bar + 1) * 240 / bpm
        while cursor < len(sources) and sources[cursor][0] <= boundary:
            at, user, text, role = sources[cursor]
            mapper.observe(user, text, at, role)
            cursor += 1
        controls.append(mapper.aggregate(boundary))
    score = compose(args.style, args.seed, bars, controls)
    wav = render_wav(score, args.output / 'demo.wav')
    midi = render_midi(score, args.output / 'demo.mid')
    (args.output / 'demo_events.json').write_text(json.dumps({'seed': args.seed, 'style': args.style, 'bpm': bpm, 'bar_seconds': 240/bpm, 'controls': controls, 'notes': score['notes']}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'wav': wav, 'midi': midi, 'bars': bars, 'simulated_users': 5}, ensure_ascii=False))


if __name__ == '__main__': main()
