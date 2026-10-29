import json
from pathlib import Path
import tempfile
import unittest
import wave
import array

from maijam.core.events import EventMapper, MapperConfig
from maijam.core.music import STYLES, compose
from maijam.core.render import render_wav, render_midi
from maijam.core.session import SessionManager


class EngineTests(unittest.TestCase):
    def test_reproducible_and_structured(self):
        controls = [{'energy': .6, 'layers': 5, 'fill': .4, 'accent': .3}]*8
        a=compose('lofi', 42, 8, controls); b=compose('lofi',42,8,controls)
        self.assertEqual(a,b)
        self.assertTrue({'drums','bass','chords','lead'} <= {n['track'] for n in a['notes']})
        self.assertTrue(all(0 <= n['start'] < 128 and n['duration'] > 0 for n in a['notes']))
        self.assertNotEqual(a,compose('house',42,8,controls))

    def test_styles_and_mixing(self):
        scores = [compose(s, 17, 4, [{'energy': .6,'layers':5}]*4) for s in STYLES]
        self.assertEqual(len({s['bpm'] for s in scores}), 4)
        self.assertEqual(len({tuple((n['start'],n['pitch'],n['wave']) for n in s['notes']) for s in scores}), 4)
        silent=compose('house',1,2,mute=['drums'])
        self.assertFalse(any(n['track']=='drums' for n in silent['notes']))

    def test_audio_and_midi(self):
        with tempfile.TemporaryDirectory() as d:
            score=compose('house',23,2,[{'energy': .5, 'layers': 5}]*2)
            wav=Path(d)/'a.wav'; midi=Path(d)/'a.mid'
            meta=render_wav(score,wav); render_midi(score,midi)
            with wave.open(str(wav),'rb') as f:
                self.assertEqual((f.getnchannels(),f.getsampwidth(),f.getframerate()),(1,2,22050))
                self.assertGreater(f.getnframes(),1000)
                pcm=array.array('h'); pcm.frombytes(f.readframes(f.getnframes()))
                self.assertGreater(max(abs(x) for x in pcm),100)
                self.assertLess(max(abs(x) for x in pcm),32767)
            self.assertGreater(meta['peak'],0); self.assertLessEqual(meta['peak'],.94)
            self.assertEqual(midi.read_bytes()[:4],b'MThd')

    def test_window_caps_privacy_and_decay(self):
        mapper=EventMapper(MapperConfig(window_seconds=10,user_cap=3,max_queue=50))
        for _ in range(300): mapper.observe('one','哈哈哈哈！',1,'drums')
        self.assertLessEqual(len(mapper.queue),50)
        loud=mapper.aggregate(2)
        self.assertEqual(loud['events'],3); self.assertGreater(loud['fill'],0)
        self.assertNotIn('哈哈',repr(mapper.queue))
        quiet=mapper.aggregate(20)
        self.assertLess(quiet['energy'],loud['energy'])
        self.assertFalse(mapper.observe('one','/jam start',21))
        self.assertFalse(mapper.observe('bot','Hello!',21,is_bot=True))

    def test_sessions_isolated_and_persistent(self):
        with tempfile.TemporaryDirectory() as d:
            m=SessionManager(d,max_members=2)
            m.start('qq','one','stream1'); m.join('qq','one','u','drums',1)
            m.observe('qq','one','u','哈哈哈',2); m.tick('qq','one',3)
            self.assertFalse(m.observe('qq','two','u','private phrase',2))
            m.start('qq','two','stream2'); self.assertFalse(m.groups['qq:two']['controls'])
            m.save(); raw=(Path(d)/'sessions.json').read_text(encoding='utf8')
            self.assertNotIn('哈哈哈',raw); self.assertNotIn('private phrase',raw)
            restored=SessionManager(d); self.assertFalse(restored.groups['qq:one']['running'])
            self.assertEqual(restored.groups['qq:one']['members']['u']['role'],'drums')

    def test_midi_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            s=compose('chiptune',123,2)
            a=Path(d)/'a.mid';b=Path(d)/'b.mid';render_midi(s,a);render_midi(s,b)
            self.assertEqual(a.read_bytes(),b.read_bytes())

    def test_many_groups_and_bounded_members(self):
        with tempfile.TemporaryDirectory() as d:
            m=SessionManager(d,max_members=2)
            m.start('qq','one','1');m.start('qq','two','2')
            m.join('qq','one','a','lead');m.join('qq','one','b','bass')
            with self.assertRaises(ValueError): m.join('qq','one','c')
            for i in range(2000): m.observe('qq','one','a','哈'*3,i/1000)
            self.assertLessEqual(len(m.mappers['qq:one'].queue),512)
            self.assertEqual(m.tick('qq','two',20)['events'],0)

    def test_layer_changes_are_quantized_and_gradual(self):
        mapper=EventMapper(MapperConfig(window_seconds=5))
        for u in range(5): mapper.observe(str(u),'✨',1,'lead')
        controls=[mapper.aggregate(2) for _ in range(5)]
        self.assertEqual([x['layers'] for x in controls],[2,3,4,5,6])
        silent=[mapper.aggregate(20) for _ in range(5)]
        self.assertEqual([x['layers'] for x in silent],[5,4,3,2,1])


if __name__=='__main__': unittest.main()
