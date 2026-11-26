#!/usr/bin/env python3
"""limits.py: how many times a caller may knock on the sign-in routes of remote access (preview).

A sign-in page on the internet is open by nature: anyone can register a client and ask for the consent page. Each route has a
window and two thresholds. Over the first, a request is slowed. Over the second, it is refused until the window moves on. One
count is per caller, and one is for all callers together, because a relay may hide who is calling: then every caller is one.

Memory is bounded: a table that grows past its cap drops its oldest callers first, and a refused request is not counted twice.
Standard library only; runs on the Python that macOS ships (3.9) as well as on the extra's own runtime.
"""
from __future__ import annotations

import collections
import sys
from typing import Deque, Dict, Tuple

sys.dont_write_bytecode = True

OK, SLOW, REFUSE = "ok", "slow", "refuse"
MAX_CALLERS = 4096


class Limiter:
    """Counts hits in a sliding window. `soft` hits are free; up to `hard` are slowed; past that they are refused."""

    def __init__(self, soft: int, hard: int, window: float, shared_hard: int = 0):
        self.soft, self.hard, self.window = soft, hard, window
        self.shared_hard = shared_hard or hard * 8
        self.callers: "collections.OrderedDict[str, Deque[float]]" = collections.OrderedDict()
        self.everyone: Deque[float] = collections.deque()

    @staticmethod
    def _trim(q: Deque[float], now: float, window: float) -> None:
        while q and q[0] <= now - window:
            q.popleft()

    def hit(self, caller: str, now: float) -> Tuple[str, float]:
        """Count one request. Returns the verdict and the seconds until the window has room again."""
        self._trim(self.everyone, now, self.window)
        q = self.callers.pop(caller, None)
        if q is None:
            q = collections.deque()
        self._trim(q, now, self.window)
        self.callers[caller] = q
        while len(self.callers) > MAX_CALLERS:
            self.callers.popitem(last=False)
        if len(q) >= self.hard or len(self.everyone) >= self.shared_hard:
            oldest = min([x[0] for x in (q, self.everyone) if x] or [now])
            return REFUSE, max(1.0, oldest + self.window - now)
        q.append(now)
        self.everyone.append(now)
        return (SLOW if len(q) > self.soft else OK), 0.0


def routes() -> Dict[str, Limiter]:
    """The sign-in routes and their limits. Registration is the one anyone can reach, so it is the tightest."""
    return {
        "/register": Limiter(soft=3, hard=8, window=600, shared_hard=40),
        "/token": Limiter(soft=30, hard=90, window=60, shared_hard=400),
        "/consent": Limiter(soft=10, hard=30, window=600, shared_hard=120),
        "/authorize": Limiter(soft=20, hard=60, window=60, shared_hard=300),
        "/revoke": Limiter(soft=20, hard=60, window=60, shared_hard=300),
    }
