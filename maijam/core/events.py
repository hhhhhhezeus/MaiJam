"""Private, bounded rule-based message features; never persists message contents."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import math
import re

LAUGH = re.compile(r'(哈{2,}|呵{2,}|[hH][aA](?:[hHaA]){2,}|[wW]{3,})')
COMMAND = re.compile(r'^\s*[/!！]')
POSITIVE = frozenset('😀😄😆😊🥰😍😎✨🎉🎵🎶💖❤🌞')
CALM = frozenset('😔😢😭😴🌧💧')


@dataclass
class MapperConfig:
    window_seconds: int = 30
    user_cap: int = 5
    max_queue: int = 512
    active_users_scale: int = 5
    energy_scale: float = 18.0
    smoothing: float = .35
    fill_scale: float = 3.0
    accent_scale: float = 8.0


class EventMapper:
    def __init__(self, config=None):
        self.cfg = config or MapperConfig()
        if not (1 <= self.cfg.window_seconds <= 600 and 1 <= self.cfg.user_cap <= 100 and 1 <= self.cfg.max_queue <= 10000 and self.cfg.active_users_scale > 0 and self.cfg.energy_scale > 0 and 0 < self.cfg.smoothing <= 1 and self.cfg.fill_scale > 0 and self.cfg.accent_scale > 0):
            raise ValueError('invalid mapper configuration')
        self.queue = deque(maxlen=self.cfg.max_queue)
        self.energy = .18
        self.layers = 1

    def observe(self, user, text, at, role='', is_bot=False):
        if is_bot or not user or not isinstance(text, str): return False
        text = text.strip()
        if not text or len(text) > 2000 or COMMAND.match(text): return False
        if len(text) >= 100 and len(set(text)) <= 2: return False
        # Store bounded numerical features only; text is discarded after this call.
        punctuation = sum(1 for c in text if c in '!！?？')
        bright = sum(1 for c in text if c in POSITIVE)
        calm = sum(1 for c in text if c in CALM)
        self.queue.append((float(at), str(user), len(text), min(8, punctuation), bool(LAUGH.search(text)), min(4, bright), min(4, calm), role))
        return True

    def aggregate(self, at):
        cutoff = float(at) - self.cfg.window_seconds
        while self.queue and self.queue[0][0] < cutoff: self.queue.popleft()
        counts = Counter(); accepted = []
        for item in self.queue:
            if cutoff <= item[0] <= at and counts[item[1]] < self.cfg.user_cap:
                accepted.append(item); counts[item[1]] += 1
        density = min(1.0, len(accepted) / self.cfg.energy_scale)
        target = .12 + .78 * density
        self.energy += self.cfg.smoothing * (target - self.energy)
        total_chars = sum(x[2] for x in accepted)
        punct = sum(x[3] for x in accepted)
        bright, calm = sum(x[5] for x in accepted), sum(x[6] for x in accepted)
        roles = Counter(x[7] for x in accepted if x[7])
        target_layers = max(1, min(6, 1 + math.ceil(len(counts) / self.cfg.active_users_scale * 5)))
        if target_layers > self.layers: self.layers += 1
        elif target_layers < self.layers: self.layers -= 1
        return {
            'energy': round(self.energy, 4),
            'fill': round(min(1.0, sum(x[4] for x in accepted) / self.cfg.fill_scale), 4),
            'accent': round(min(1.0, punct / self.cfg.accent_scale), 4),
            'brightness': round(max(-1., min(1., (bright - calm) / max(1, bright + calm))), 4),
            'layers': self.layers,
            'participants': len(counts), 'events': len(accepted),
            'mean_length': round(total_chars / max(1, len(accepted)), 2),
            'punctuation_density': round(punct / max(1, total_chars), 4),
            'roles': dict(roles),
        }
