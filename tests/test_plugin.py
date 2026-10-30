"""Integration against the installed real SDK with simulated Host context."""
import asyncio
import logging
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import inspect

from MaiJam.plugin import create_plugin


class FakeSend:
    def __init__(self): self.sent=[]
    async def text(self, text, stream_id, **kwargs):
        self.sent.append((text,stream_id)); return True


class PluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.send=FakeSend()
        self.plugin=create_plugin()
        self.plugin.set_plugin_config({'plugin':{'config_version':'1.0.0','admins':['qq:admin'],'bot_ids':['qq:bot'],'cooldown_seconds':0}})
        self.plugin._set_context(SimpleNamespace(paths=SimpleNamespace(data_dir=Path(self.tmp.name)),logger=logging.getLogger('test'),send=self.send))
        await self.plugin.on_load()

    async def asyncTearDown(self):
        await self.plugin.on_unload(); self.tmp.cleanup()

    async def command(self, args, user='admin', group='group'):
        return await self.plugin.command(stream_id='stream',matched_groups={'args':args},platform='qq',group_id=group,user_id=user)

    async def test_components_lifecycle_and_safe_default(self):
        components=self.plugin.get_components()
        names={c['name'] for c in components}
        self.assertTrue({'jam','jam_observer','studio_snapshot','studio_control','audio_chunk'}<=names)
        self.assertFalse(self.plugin.manager.groups)
        await self.command('start', user='not-admin')
        self.assertIn('权限', self.send.sent[-1][0]); self.assertFalse(self.plugin.manager.groups)
        await self.command('start'); await self.command('join drums',user='member')
        message={'platform':'qq','message_info':{'group_info':{'group_id':'group'},'user_info':{'user_id':'member'}},'raw_message':[{'type':'text','data':{'text':'哈哈哈哈！'}}]}
        self.assertIsNone(await self.plugin.observe(message))
        c=self.plugin.manager.tick('qq','group',__import__('time').time())
        self.assertGreater(c['fill'],0)
        bot={'platform':'qq','message_info':{'group_info':{'group_id':'group'},'user_info':{'user_id':'bot'}},'raw_message':'哈哈哈'}
        n=len(self.plugin.manager.mappers['qq:group'].queue)
        await self.plugin.observe(bot); self.assertEqual(n,len(self.plugin.manager.mappers['qq:group'].queue))
        await self.command('stop'); self.assertFalse(self.plugin.manager.groups['qq:group']['running'])

    async def test_webui_controls_change_real_state(self):
        await self.command('start')
        await self.plugin.studio_control('qq:group','style','house')
        await self.plugin.studio_control('qq:group','mute','drums')
        await self.plugin.studio_control('qq:group','level','lead:0.5')
        state=(await self.plugin.studio_snapshot())['groups'][0]
        self.assertEqual(state['style'],'house'); self.assertIn('drums',state['mute']); self.assertEqual(state['levels']['lead'],.5)
        await self.plugin.studio_control('qq:group','stop')
        self.assertFalse(self.plugin.manager.groups['qq:group']['running'])

    async def test_host_filter_and_no_audio_claim(self):
        await self.command('start')
        await self.plugin.observe({'platform':'qq','message_info':{'group_info':{'group_id':'other'},'user_info':{'user_id':'a'}},'raw_message':'hello'})
        self.assertNotIn('qq:other',self.plugin.manager.groups)
        await self.command('export wav')
        self.assertIn('没有录制',self.send.sent[-1][0])

    async def test_record_creates_audio_and_midi(self):
        await self.command('start')
        await self.command('record 5')
        task=self.plugin.jobs['qq:group']
        await asyncio.wait_for(asyncio.shield(task), timeout=15)
        session=self.plugin.manager.groups['qq:group']
        self.assertTrue(session['last_file'])
        self.assertEqual(self.plugin.recording_status('qq:group')['stage'], 'completed')
        self.assertEqual(self.plugin.recordings('qq','group')[0]['id'], session['last_file'])
        folder=self.plugin.manager.safe_export_dir('qq','group')
        self.assertTrue((folder / (session['last_file']+'.wav')).is_file())
        self.assertTrue((folder / (session['last_file']+'.mid')).is_file())
        part=await self.plugin.audio_chunk('qq:group',0)
        self.assertTrue(part['base64']); self.assertGreater(part['next'],0)
        await self.command('export wav')
        self.assertIn('没有已验证的通用音频发送接口',self.send.sent[-1][0])

    async def test_stop_cancels_recording(self):
        await self.command('start'); await self.command('record 5')
        job=self.plugin.jobs['qq:group']; await asyncio.sleep(.02)
        await self.command('stop'); await asyncio.gather(job,return_exceptions=True)
        self.assertFalse(self.plugin.manager.groups['qq:group']['last_file'])

    async def test_cancel_requires_admin_and_keeps_session_running(self):
        await self.command('start'); await self.command('record 5')
        job = self.plugin.jobs['qq:group']
        await self.command('cancel', user='member')
        self.assertIn('权限', self.send.sent[-1][0])
        self.assertFalse(job.cancelled())
        await self.command('cancel')
        self.assertTrue(job.cancelled())
        self.assertTrue(self.plugin.manager.groups['qq:group']['running'])
        self.assertNotIn('qq:group', self.plugin.jobs)
        self.assertFalse(self.plugin.manager.groups['qq:group']['last_file'])
        await self.command('cancel')
        self.assertIn('没有录制', self.send.sent[-1][0])
        await self.command('record 5')
        await asyncio.sleep(.02)
        await self.plugin.studio_control('qq:group', 'cancel')
        self.assertNotIn('qq:group', self.plugin.jobs)
        self.assertTrue(self.plugin.manager.groups['qq:group']['running'])

    async def test_history_scoped_and_validated(self):
        await self.command('start')
        folder = self.plugin.manager.safe_export_dir('qq', 'group')
        (folder/'jam-123.wav').write_bytes(b'test-audio')
        (folder/'jam-123.mid').write_bytes(b'midi')
        records = self.plugin.recordings('qq', 'group')
        self.assertEqual([r['id'] for r in records], ['jam-123'])
        part = await self.plugin.audio_chunk('qq:group', 0, 'jam-123')
        self.assertTrue(part['done'])
        await self.command('start', group='other')
        self.assertEqual(self.plugin.recordings('qq', 'other'), [])
        for key, recording in [('qq:group','../jam-123'), ('qq:other','jam-123')]:
            with self.assertRaises(ValueError): await self.plugin.audio_chunk(key, 0, recording)
        await self.command('history', user='member')
        self.assertIn('权限', self.send.sent[-1][0])
        await self.command('history')
        self.assertIn('jam-123', self.send.sent[-1][0])
        await self.command('export wav jam-123')
        self.assertIn('jam-123.wav', self.send.sent[-1][0])
        await self.command('record 5')
        status = self.plugin.recording_status('qq:group')
        self.assertEqual(status['stage'], 'collecting')
        self.assertLessEqual(status['remaining_seconds'], 5)
        await self.command('cancel')
        self.assertEqual(self.plugin.recording_status('qq:group')['stage'], 'cancelled')

    async def test_hot_config_update_and_no_llm(self):
        self.plugin.set_plugin_config({'plugin':{'config_version':'1.0.0','admins':['qq:admin'],'bot_ids':['qq:bot'],'user_cap':2}})
        await self.plugin.on_config_update('self',{},'1.0.0')
        await self.command('start')
        self.assertEqual(self.plugin.manager.mappers['qq:group'].cfg.user_cap,2)
        self.assertNotIn('.ctx.llm', inspect.getsource(type(self.plugin)))


if __name__=='__main__': unittest.main()
