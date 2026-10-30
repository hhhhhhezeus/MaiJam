"""MaiJam SDK adapter; no LLM or host-internal imports."""
from __future__ import annotations

import asyncio
import base64
import math
import re
import time
from pathlib import Path
from typing import Any

from maibot_sdk import API, Command, EventHandler, Field, MaiBotPlugin, PluginConfigBase
from maibot_sdk.types import EventType

from .maijam.core.events import MapperConfig
from .maijam.core.music import STYLES, TRACKS, compose
from .maijam.core.render import render_midi, render_wav
from .maijam.core.session import SessionManager
from .maijam.adapters.audio_delivery import delivery_status


class JamSettings(PluginConfigBase):
    config_version: str = Field(default='1.0.0', description='配置版本')
    admins: list[str] = Field(default_factory=list, description='管理白名单，例如 qq:123456；空列表拒绝群内管理')
    bot_ids: list[str] = Field(default_factory=list, description='机器人身份，例如 qq:3663187956；用于过滤自身消息')
    window_seconds: int = Field(default=30, ge=5, le=300, description='消息聚合窗口秒数')
    user_cap: int = Field(default=5, ge=1, le=30, description='每人每窗口的最大贡献数')
    max_queue: int = Field(default=512, ge=32, le=5000, description='每群内存事件上限')
    energy_scale: float = Field(default=18.0, gt=0, le=500, description='能量达到满值所需消息数')
    smoothing: float = Field(default=.35, gt=0, le=1, description='能量变化平滑比例')
    fill_scale: float = Field(default=3.0, gt=0, le=100, description='笑声填充达到满值所需次数')
    accent_scale: float = Field(default=8.0, gt=0, le=100, description='重音达到满值所需标点数')
    active_users_scale: int = Field(default=5, ge=1, le=100, description='达到最大层数所需活跃人数')
    max_members: int = Field(default=32, ge=1, le=100, description='每群成员上限')
    sleep_seconds: int = Field(default=900, ge=30, le=86400, description='成员休眠时间')
    cooldown_seconds: int = Field(default=30, ge=0, le=3600, description='录制冷却时间')
    max_record_seconds: int = Field(default=60, ge=5, le=60, description='单次录制上限')
    max_parallel_recordings: int = Field(default=2, ge=1, le=4, description='同时录制任务上限')
    retention_days: int = Field(default=7, ge=1, le=90, description='导出文件保留天数')


class JamConfig(PluginConfigBase):
    plugin: JamSettings = Field(default_factory=JamSettings)


def message_parts(message, kwargs):
    m = message if isinstance(message, dict) else {}
    info = m.get('message_info') if isinstance(m.get('message_info'), dict) else {}
    user = info.get('user_info') if isinstance(info.get('user_info'), dict) else m.get('user_info', {})
    group = info.get('group_info') if isinstance(info.get('group_info'), dict) else m.get('group_info', {})
    user = user if isinstance(user, dict) else {}
    group = group if isinstance(group, dict) else {}
    platform = str(kwargs.get('platform') or m.get('platform') or info.get('platform') or '')
    uid = str(kwargs.get('user_id') or user.get('user_id') or '')
    gid = str(kwargs.get('group_id') or group.get('group_id') or '')
    raw = kwargs.get('plain_text') or kwargs.get('raw_message') or m.get('processed_plain_text') or m.get('plain_text') or m.get('raw_message') or ''
    if isinstance(raw, list):
        bits = []
        for segment in raw:
            if not isinstance(segment, dict) or segment.get('type') != 'text': continue
            value = segment.get('data', segment.get('content', ''))
            bits.append(str(value.get('text', '') if isinstance(value, dict) else value))
        raw = ''.join(bits)
    if not isinstance(raw, str): raw = ''
    bot = bool(user.get('is_bot') or m.get('is_bot'))
    return platform, gid, uid, raw, bot


class MaiJam(MaiBotPlugin):
    config_model = JamConfig

    def mapper_config(self):
        c = self.config.plugin
        return MapperConfig(c.window_seconds, c.user_cap, c.max_queue, c.active_users_scale, c.energy_scale, c.smoothing, c.fill_scale, c.accent_scale)

    async def on_load(self):
        self.manager = SessionManager(self.ctx.paths.data_dir, self.mapper_config(), self.config.plugin.max_members, self.config.plugin.sleep_seconds)
        self.manager.cleanup(self.config.plugin.retention_days * 86400)
        self.jobs = {}; self.record_states = {}; self.deadlines = {}; self.closing = False
        self.ticker = asyncio.create_task(self._ticker(), name='maijam-ticker')
        self.cleaner = asyncio.create_task(self._cleaner(), name='maijam-cleaner')

    async def on_unload(self):
        self.closing = True
        self.ticker.cancel()
        self.cleaner.cancel()
        await asyncio.gather(self.ticker, self.cleaner, return_exceptions=True)
        # A running render is shielded: wait for the worker to finish before closing resources.
        for task in list(self.jobs.values()): task.cancel()
        await asyncio.gather(*list(self.jobs.values()), return_exceptions=True)
        for session in self.manager.groups.values(): session['running'] = False
        self.manager.save()

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str):
        if scope == 'self':
            self.manager.set_mapper_config(self.mapper_config())
            self.manager.max_members = self.config.plugin.max_members
            self.manager.sleep_seconds = self.config.plugin.sleep_seconds

    async def _ticker(self):
        while True:
            now = time.time()
            for key, session in list(self.manager.groups.items()):
                if not session['running']:
                    self.deadlines.pop(key, None); continue
                seconds = 240 / STYLES[session['style']]['bpm']
                deadline = self.deadlines.setdefault(key, now + seconds)
                if now >= deadline:
                    self.manager.tick(session['platform'], session['group_id'], now)
                    self.deadlines[key] = now + seconds
                    self.manager.save()
            await asyncio.sleep(.25)

    async def _cleaner(self):
        while True:
            await asyncio.sleep(3600)
            await asyncio.to_thread(self.manager.cleanup, self.config.plugin.retention_days * 86400)

    @EventHandler('jam_observer', description='以非拦截模式观察消息', event_type=EventType.ON_MESSAGE, intercept_message=False)
    async def observe(self, message=None, **kwargs):
        p, g, u, text, is_bot = message_parts(message, kwargs)
        if not (p and g and u): return None
        info = message.get('message_info', {}) if isinstance(message, dict) else {}
        extra = info.get('additional_config', {}) if isinstance(info, dict) else {}
        if not isinstance(extra, dict): extra = {}
        self_id = str((extra or {}).get('self_id', '') or (message.get('self_id', '') if isinstance(message, dict) else ''))
        bot_ids = set(self.config.plugin.bot_ids)
        if not self_id and not bot_ids:
            return None  # Fail closed when the platform does not identify its own bot.
        self.manager.observe(p, g, u, text, time.time(), is_bot or u == self_id or f'{p}:{u}' in bot_ids)
        return None

    def is_admin(self, platform, user):
        return f'{platform}:{user}' in self.config.plugin.admins

    async def send(self, stream, text):
        if stream: await self.ctx.send.text(text, stream)
        return True, '', 2

    def begin_record(self, p, g, seconds):
        key = self.manager.key(p, g); s = self.manager.ensure(p, g)
        if not s['running']: raise ValueError('请先由管理员 /jam start。')
        if not 5 <= seconds <= self.config.plugin.max_record_seconds: raise ValueError('录制时长超出配置范围。')
        if key in self.jobs and not self.jobs[key].done(): raise ValueError('本群已有录制任务。')
        if sum(not task.done() for task in self.jobs.values()) >= self.config.plugin.max_parallel_recordings: raise ValueError('录制任务已达到全局上限，请稍后再试。')
        if time.time() - s['last_export'] < self.config.plugin.cooldown_seconds: raise ValueError('录制冷却中。')
        s['last_export'] = time.time(); self.manager.save()
        self.record_states[key] = {'stage': 'collecting', 'deadline': time.monotonic() + seconds}
        self.jobs[key] = asyncio.create_task(self._record(p, g, seconds), name='maijam-record')

    async def cancel_record(self, p, g):
        key = self.manager.key(p, g)
        task = self.jobs.get(key)
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        # A task cancelled before its first step never executes its finally block.
        if self.jobs.get(key) is task:
            self.jobs.pop(key, None)
        self.record_states[key] = {'stage': 'cancelled'}
        return True

    def recording_status(self, key):
        status = dict(self.record_states.get(key, {'stage': 'idle'}))
        if status['stage'] == 'collecting':
            status['remaining_seconds'] = max(0, math.ceil(status.pop('deadline') - time.monotonic()))
        return status

    def recordings(self, p, g):
        folder = self.manager.safe_export_dir(p, g, create=False)
        if folder.is_symlink() or folder.parent.is_symlink() or not folder.is_dir():
            return []
        records = []
        active = self.record_states.get(self.manager.key(p, g), {})
        for wav in folder.glob('jam-*.wav'):
            if active.get('stage') == 'rendering' and active.get('recording') == wav.stem: continue
            midi = wav.with_suffix('.mid')
            if not re.fullmatch(r'jam-\d+', wav.stem) or wav.is_symlink() or midi.is_symlink():
                continue
            try:
                if not wav.is_file() or not midi.is_file(): continue
                stat = wav.stat()
                records.append({'id': wav.stem, 'created_at': stat.st_mtime, 'bytes': stat.st_size})
            except FileNotFoundError:
                continue
        return sorted(records, key=lambda item: item['created_at'], reverse=True)[:24]

    async def _record(self, p, g, seconds):
        key = self.manager.key(p, g); s = self.manager.ensure(p, g)
        try:
            start_bar = s['bar']; start_style = s['style']; started = time.monotonic()
            while time.monotonic() - started < seconds:
                await asyncio.sleep(min(1, seconds - (time.monotonic() - started)))
                if self.closing or not s['running']: raise asyncio.CancelledError
            if s['style'] != start_style: raise ValueError('录制期间风格改变，请重新录制。')
            self.record_states[key] = {'stage': 'rendering'}
            count = max(1, math.floor(seconds * STYLES[start_style]['bpm'] / 240))
            available = min(count, max(0, s['bar'] - start_bar))
            controls = list(s['controls'][-available:]) if available else []
            controls = [controls[0] if controls else {'energy': .18, 'layers': 1}] * (count-len(controls)) + controls
            score = compose(start_style, s['seed'] + start_bar, count, controls, mute=s['mute'], levels=s['levels'])
            folder = self.manager.safe_export_dir(p, g)
            stem = 'jam-' + str(time.time_ns())
            self.record_states[key]['recording'] = stem
            wav, midi = folder / (stem+'.wav'), folder / (stem+'.mid')
            def work():
                try:
                    render_wav(score, wav, max_seconds=65)
                    render_midi(score, midi)
                    if wav.stat().st_size > 4_000_000: raise ValueError('导出文件超过大小限制。')
                except BaseException:
                    wav.unlink(missing_ok=True); midi.unlink(missing_ok=True)
                    raise
            task = asyncio.create_task(asyncio.to_thread(work))
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=120)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                # Python worker threads cannot be cancelled; wait, then remove incomplete output.
                await asyncio.shield(task)
                wav.unlink(missing_ok=True); midi.unlink(missing_ok=True)
                raise
            s['last_file'] = stem; self.manager.save()
            self.record_states[key] = {'stage': 'completed', 'recording': stem}
            self.manager.cleanup(self.config.plugin.retention_days * 86400)
            if s.get('stream_id'):
                try:
                    await self.ctx.send.text('🎵 录制完成。'+delivery_status()['message'], s['stream_id'])
                except Exception:
                    self.ctx.logger.warning('录音已保存，但完成通知发送失败。', exc_info=True)
        except asyncio.CancelledError:
            self.record_states[key] = {'stage': 'cancelled'}
            raise
        except Exception as exc:
            self.record_states[key] = {'stage': 'failed', 'error': str(exc)[:160]}
            self.ctx.logger.exception('MaiJam 录制失败')
            if s.get('stream_id'):
                await self.ctx.send.text('🎵 录制失败：'+str(exc)[:160], s['stream_id'])
        finally:
            self.jobs.pop(key, None)

    @Command('jam', description='群聊协作音乐', pattern=r'^/jam(?:\s+(?P<args>.*))?$')
    async def command(self, stream_id='', message=None, matched_groups=None, **kwargs):
        p, g, u, _, _ = message_parts(message, kwargs)
        if not (p and g and u): return await self.send(stream_id, 'MaiJam 仅支持可识别用户的群聊。')
        args = str((matched_groups or {}).get('args') or '').split()
        action = args[0].lower() if args else 'help'
        try:
            if action in ('start', 'stop', 'style', 'record', 'cancel', 'export', 'history') and not self.is_admin(p, u):
                raise ValueError('需要插件配置的管理员白名单权限。')
            s = self.manager.ensure(p, g)
            if action == 'start':
                if f'{p}:{u}' in self.config.plugin.bot_ids: raise ValueError('机器人不能作为管理员。')
                self.manager.start(p, g, stream_id)
                text = '🎵 MaiJam 已开启。群友发送 /jam join 加入。请确认已配置 bot_ids。'
            elif action == 'stop':
                self.manager.stop(p, g)
                await self.cancel_record(p, g)
                text = '🎵 会话已停止，待完成的录制已取消。'
            elif action == 'join':
                self.manager.join(p, g, u, args[1] if len(args)>1 else 'lead')
                text = '🎵 已加入，使用 /jam instrument <乐器> 切换。'
            elif action == 'leave':
                text = '🎵 已退出。' if self.manager.leave(p,g,u) else '你还没有加入乐队。'
            elif action == 'instrument':
                if u not in s['members']: raise ValueError('请先 /jam join。')
                if len(args)<2: raise ValueError('用法：/jam instrument drums|bass|lead|chords|arp|fx')
                self.manager.join(p,g,u,args[1]); text = '🎵 乐器已切换为 '+args[1]
            elif action == 'members':
                now=time.time(); members=[f"{uid}: {m['role']}"+('（休眠）' if now-m['last_active']>self.manager.sleep_seconds else '') for uid,m in s['members'].items()]
                text = '🎵 成员：\n' + ('\n'.join(members) if members else '暂无')
            elif action == 'style':
                if len(args)<2: raise ValueError('用法：/jam style lofi|synthwave|chiptune|house')
                self.manager.style(p,g,args[1]); text = '🎵 风格已切换为 '+args[1]+'，从下一小节生效。'
            elif action == 'record':
                if len(args)<2 or not args[1].isdigit(): raise ValueError('用法：/jam record 30')
                self.begin_record(p,g,int(args[1])); text = '🎵 开始记录聚合状态，完成后在插件数据目录导出 WAV 和 MIDI。'
            elif action == 'cancel':
                cancelled = await self.cancel_record(p, g)
                text = '🎵 录制已取消，乐队继续演奏。' if cancelled else '🎵 当前没有录制任务。'
            elif action == 'history':
                records = self.recordings(p, g)
                text = '🎵 历史录音：\n' + ('\n'.join(x['id'] for x in records) if records else '暂无已完成的录音。')
            elif action == 'export':
                kind = args[1].lower() if len(args)>1 else ''
                if kind not in ('wav','midi'): raise ValueError('用法：/jam export wav|midi')
                recording = args[2] if len(args) > 2 else s['last_file']
                if recording and not re.fullmatch(r'jam-\d+', recording): raise ValueError('录音编号无效。')
                if not recording: raise ValueError('还没有录制，请先 /jam record 30。')
                path = self.manager.safe_export_dir(p,g) / (recording + ('.mid' if kind=='midi' else '.wav'))
                if path.is_symlink() or not path.is_file(): raise ValueError('文件不存在或已按保留策略清理。')
                text = '🎵 导出文件位于宿主插件数据目录：'+str(path)+'\n'+delivery_status()['message']
            elif action == 'status':
                c=s['controls'][-1] if s['controls'] else {}; text=f"🎵 {'进行中' if s['running'] else '已停止'} · {s['style']} · {STYLES[s['style']]['bpm']} BPM · 小节 {s['bar']} · 能量 {c.get('energy',0):.2f}"
                state = self.recording_status(self.manager.key(p, g))
                labels = {'idle':'未录制','collecting':'收集中','rendering':'生成音频中','completed':'完成','cancelled':'已取消','failed':'失败'}
                text += '\n录制：' + labels[state['stage']] + (f"，剩余 {state['remaining_seconds']} 秒" if 'remaining_seconds' in state else '')
            else:
                text='🎵 /jam start|stop|status|join|leave|members\n/jam instrument drums|bass|lead|chords|arp|fx\n/jam style lofi|synthwave|chiptune|house\n/jam record 30 · /jam cancel · /jam history · /jam export wav|midi [录音编号]\nstart、stop、style、record、cancel、export、history 需要管理员白名单。'
            return await self.send(stream_id,text)
        except (ValueError, OSError) as e:
            return await self.send(stream_id,'🎵 '+str(e))

    @API('studio_snapshot', version='1')
    async def studio_snapshot(self):
        result=[]
        for key,s in self.manager.groups.items():
            result.append({'key': key, 'platform': s['platform'], 'group_id': s['group_id'], 'running': s['running'], 'style': s['style'], 'bpm': STYLES[s['style']]['bpm'], 'root': STYLES[s['style']]['key'], 'bar': s['bar'], 'control': s['controls'][-1] if s['controls'] else {}, 'members': s['members'], 'levels': s['levels'], 'mute': s['mute'], 'last_file': bool(s['last_file']), 'recording': key in self.jobs, 'record_status': self.recording_status(key), 'recordings': self.recordings(s['platform'], s['group_id'])})
        return {'groups': result, 'tracks': list(TRACKS), 'styles': list(STYLES)}

    @API('studio_control', version='1')
    async def studio_control(self, group: str, operation: str, value: str = ''):
        s=self.manager.groups.get(group)
        if not s: raise ValueError('群不存在。请先在群中发送 /jam start。')
        p,g=s['platform'],s['group_id']
        if operation=='start': self.manager.start(p,g,s['stream_id'])
        elif operation=='stop':
            self.manager.stop(p,g)
            await self.cancel_record(p, g)
        elif operation=='style': self.manager.style(p,g,value)
        elif operation=='record': self.begin_record(p,g,int(value))
        elif operation=='cancel': await self.cancel_record(p,g)
        elif operation=='mute':
            if value not in TRACKS: raise ValueError('未知声部。')
            s['mute'] = [x for x in s['mute'] if x != value] if value in s['mute'] else s['mute']+[value]
            self.manager.save()
        elif operation=='level':
            track, sep, level = value.partition(':')
            if not sep or track not in TRACKS: raise ValueError('音量参数无效。')
            number=float(level)
            if not math.isfinite(number) or not 0 <= number <= 1.5: raise ValueError('音量范围为 0–1.5。')
            s['levels'][track]=number; self.manager.save()
        else: raise ValueError('未知操作。')
        return {'ok': True}

    @API('audio_chunk', version='1')
    async def audio_chunk(self, group: str, offset: int = 0, recording: str = ""):
        s=self.manager.groups.get(group)
        if not s or not (recording or s['last_file']) or offset < 0 or offset > 4_000_000: raise ValueError('没有可播放的录音。')
        recording = recording or s['last_file']
        if not re.fullmatch(r'jam-\d+', recording): raise ValueError('录音编号无效。')
        path=self.manager.safe_export_dir(s['platform'],s['group_id']) / (recording+'.wav')
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4_000_000: raise ValueError('录音已清理或超过上限。')
        with path.open('rb') as f:
            f.seek(offset); data=f.read(96000)
        return {'base64':base64.b64encode(data).decode('ascii'), 'next':offset+len(data), 'done':offset+len(data)>=path.stat().st_size}


def create_plugin():
    return MaiJam()
