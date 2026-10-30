"""Per-group state and bounded control history; chats are never stored."""
from __future__ import annotations

from collections import deque
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time

from .events import EventMapper, MapperConfig
from .music import STYLES, TRACKS


class SessionManager:
    def __init__(self, root, mapper_config=None, max_members=32, sleep_seconds=900):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'sessions.json'
        self.groups = {}
        self.mappers = {}
        self.mapper_config = mapper_config or MapperConfig()
        self.max_members = max(1, min(100, int(max_members)))
        self.sleep_seconds = max(30, int(sleep_seconds))
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(data, dict): self.groups = data
        # Queue and ongoing jobs are intentionally not restored. Sessions resume in stopped state.
        for s in self.groups.values(): s['running'] = False

    @staticmethod
    def key(platform, group):
        if not platform or not group: raise ValueError('仅支持群聊。')
        return f'{platform}:{group}'

    def ensure(self, platform, group):
        key = self.key(platform, group)
        if key not in self.groups:
            if len(self.groups) >= 256:
                raise ValueError('群会话数量达到上限。')
            self.groups[key] = {'platform': str(platform), 'group_id': str(group), 'enabled': False, 'running': False,
                                'style': 'lofi', 'seed': int.from_bytes(os.urandom(4), 'big'), 'members': {},
                                'controls': [], 'bar': 0, 'mute': [], 'levels': {t: 1.0 for t in TRACKS},
                                'last_export': 0.0, 'last_file': '', 'stream_id': ''}
        if key not in self.mappers: self.mappers[key] = EventMapper(self.mapper_config)
        return self.groups[key]

    def save(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.groups, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, self.path)

    def set_mapper_config(self, cfg):
        self.mapper_config = cfg
        for mapper in self.mappers.values():
            mapper.cfg = cfg
            mapper.queue = deque(mapper.queue, maxlen=cfg.max_queue)

    def start(self, platform, group, stream):
        s = self.ensure(platform, group)
        s['enabled'] = s['running'] = True
        s['stream_id'] = str(stream)
        self.save(); return s

    def stop(self, platform, group):
        s = self.ensure(platform, group)
        s['running'] = False
        self.mappers[self.key(platform, group)].queue.clear()
        self.save(); return s

    def join(self, platform, group, user, role='lead', now=None):
        s = self.ensure(platform, group)
        if not s['enabled']: raise ValueError('本群尚未启用 MaiJam。')
        if role not in TRACKS: raise ValueError('乐器可选：' + ', '.join(TRACKS))
        user = str(user)
        if user not in s['members'] and len(s['members']) >= self.max_members: raise ValueError('乐队成员已满。')
        s['members'][user] = {'role': role, 'last_active': float(now or time.time())}
        self.save()

    def leave(self, platform, group, user):
        s = self.ensure(platform, group)
        existed = s['members'].pop(str(user), None) is not None
        self.save(); return existed

    def observe(self, platform, group, user, text, at, is_bot=False):
        key = self.key(platform, group)
        s = self.groups.get(key)
        if not s or not s['enabled'] or not s['running']: return False
        member = s['members'].get(str(user))
        role = member['role'] if member else ''
        accepted = self.mappers[key].observe(user, text, at, role, is_bot)
        if accepted and member: member['last_active'] = float(at)
        return accepted

    def tick(self, platform, group, at):
        s = self.ensure(platform, group)
        if not s['running']: return None
        control = self.mappers[self.key(platform, group)].aggregate(at)
        active = {user: member['role'] for user, member in s['members'].items() if at - member['last_active'] <= self.sleep_seconds}
        control['active_members'] = len(active)
        # Event roles are merged and capped by mapper.user_cap, not allocated as new tracks.
        s['controls'].append(control)
        s['controls'] = s['controls'][-256:]
        s['bar'] += 1
        return control

    def style(self, platform, group, name):
        if name not in STYLES: raise ValueError('风格可选：' + ', '.join(STYLES))
        s = self.ensure(platform, group)
        if not s['enabled']: raise ValueError('本群尚未启用 MaiJam。')
        s['style'] = name; self.save()

    def safe_export_dir(self, platform, group, *, create=True):
        group_hash = hashlib.sha256(self.key(platform, group).encode()).hexdigest()[:24]
        result = self.root / 'exports' / group_hash
        if create:
            result.mkdir(parents=True, exist_ok=True)
        return result

    def cleanup(self, max_age_seconds=7*86400, max_files=24, now=None):
        now = now or time.time()
        base = self.root / 'exports'
        if not base.exists(): return 0
        removed = 0
        for folder in base.iterdir():
            if not folder.is_dir() or folder.is_symlink(): continue
            files = sorted((x for x in folder.iterdir() if x.is_file() and not x.is_symlink() and x.suffix in ('.wav', '.mid', '.json')), key=lambda x: x.stat().st_mtime, reverse=True)
            for index, file in enumerate(files):
                if index >= max_files or now - file.stat().st_mtime > max_age_seconds:
                    file.unlink(); removed += 1
        return removed
