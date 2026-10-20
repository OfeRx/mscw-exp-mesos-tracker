"""Session bookkeeping: EXP gained across level-ups, meso and potion changes, and rates.

Nothing here touches the screen and the clock is passed in, so it can all be tested without
the game running."""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass

PCT_STEP = 0.01          # the game shows EXP % with two decimals
LEVEL_UP_DROP = 50       # a drop of more % than this can't be a death penalty
BIG_JUMP = 0.1           # more of a level than this in one reading needs confirming
ROLLING_SECONDS = 300    # the "last 5 minutes" rate
BIG_DROP = 15            # more potions gone than this in one reading: not drunk


def exp_bounds(exp, pct):
    """The range of EXP-needed-for-this-level that one reading allows. The shown % may be
    rounded or cut off, so the true % lies a little either side of it."""
    p_lo, p_hi = pct - PCT_STEP / 2, pct + PCT_STEP
    lo = exp * 100 / p_hi
    hi = exp * 100 / p_lo if p_lo > 0 else math.inf
    return lo, hi


def match_level(table, lo, hi):
    """The level whose EXP to next level lies between lo and hi, if exactly one does. Each
    level needs about 10% more than the last, so one reading's % pins it down."""
    hits = [level for level, need in table.items() if lo <= need <= hi]
    return hits[0] if len(hits) == 1 else None


def level_of(exp, pct, table):
    """The level for one reading of the EXP bar, if the EXP table is known."""
    return match_level(table, *exp_bounds(exp, pct)) if table and pct > 0 else None


@dataclass
class _Reading:
    exp: int
    pct: float
    lo: float
    hi: float


def _overlap(lo1, hi1, lo2, hi2):
    return max(lo1, lo2) <= min(hi1, hi2) * (1 + 1e-9)


class ExpTracker:
    """Turns successive (EXP, %) readings into EXP gained.

    Within a level the EXP needed is fixed, so every reading narrows down the range it can be
    in; a reading outside that range is a misread, a level-up or a death. Anything other than
    a plain, consistent, modest increase is only believed once a later reading shows more EXP
    on top of it: the same reading again proves nothing, since a misread repeats for as long
    as the screen doesn't change."""

    def __init__(self, table=None):
        self.table = table or {}             # level -> EXP to next level, when known
        self.cur: _Reading | None = None
        self.lo, self.hi = 0.0, math.inf     # EXP needed for the current level is in here
        self.levels = 0
        self._pending = None                 # (kind, reading) waiting for the next one to agree

    @property
    def exp(self):
        return self.cur.exp if self.cur else None

    @property
    def pct(self):
        return self.cur.pct if self.cur else None

    def level(self):
        """The current level, worked out from the EXP table, or None."""
        if self.cur is None or not self.table:
            return None
        return match_level(self.table, self.lo, self.hi)

    def needed(self):
        """EXP needed for the current level: exact from the EXP table once the level is known,
        else estimated from the %, or None if not known yet."""
        level = self.level()
        if level:
            return self.table[level]
        if self.cur is None or math.isinf(self.hi):
            return None
        return (self.lo + self.hi) / 2

    def remaining(self):
        n = self.needed()
        return None if n is None else max(0.0, n - self.cur.exp)

    def update(self, exp, pct):
        """Feed one reading. Returns the EXP gained since the last believed reading (negative
        after a death), or 0 when nothing changed or the reading isn't believed (yet)."""
        r = _Reading(exp, pct, *exp_bounds(exp, pct))
        if self.cur is None:
            self._reset(r)
            return 0
        if exp == self.cur.exp and pct == self.cur.pct:
            self._pending = None             # back to what we had: the odd one was a misread
            return 0
        gain = 0
        if self._pending:
            kind, p = self._pending
            self._pending = None
            if r.exp > p.exp and _overlap(p.lo, p.hi, r.lo, r.hi):
                gain += self._apply(kind, p)
            elif r.exp == p.exp and r.pct == p.pct:
                self._pending = (kind, p)        # unchanged: still waiting
                return gain
        kind = self._classify(r)
        if kind == "same":
            gain += self._apply("same", r)
        else:
            self._pending = (kind, r)
        return gain

    def _classify(self, r):
        c = self.cur
        consistent = _overlap(self.lo, self.hi, r.lo, r.hi)
        if r.exp >= c.exp and r.pct >= c.pct and consistent:
            needed = self.needed()
            if needed and r.exp - c.exp > BIG_JUMP * needed:
                return "jump"
            return "same"
        if r.exp < c.exp and r.pct < c.pct:
            if c.pct - r.pct > LEVEL_UP_DROP or not consistent:
                return "level"
            return "death"
        return "resync"

    def _apply(self, kind, r):
        c = self.cur
        if kind in ("same", "jump", "death"):
            self.lo, self.hi = max(self.lo, r.lo), min(self.hi, r.hi)
            self.cur = r
            return r.exp - c.exp
        if kind == "level":
            needed = self.needed()
            if needed is None:
                needed = c.exp * 100 / c.pct if c.pct > 0 else c.exp
            self.levels += 1
            self._reset(r)
            return round(max(0.0, needed - c.exp)) + r.exp
        # "resync": confirmed, but it doesn't fit the level we were in, so one of the two
        # readings was wrong and there's no telling how much EXP really came in between.
        # Count none (a little lost beats a lot invented) and start over from here.
        self._reset(r)
        return 0

    def _reset(self, r):
        self.cur = r
        self.lo, self.hi = r.lo, r.hi


class Stable:
    """Believes a changed value once it has been read the same way twice in a row."""

    def __init__(self, value=None):
        self.value = value
        self._last = None

    def feed(self, v):
        """Returns the new value when one is accepted, else None."""
        if v is None:
            return None
        if v == self.value:
            self._last = None
            return None
        if v == self._last:
            self.value, self._last = v, None
            return v
        self._last = v
        return None


@dataclass
class PotionState:
    name: str
    price: int
    start: int | None = None    # None until the count has been read once
    count: int | None = None
    used: int = 0               # count went down a little at a time: drunk
    added: int = 0              # count went up: bought or looted
    removed: int = 0            # count dropped a lot at once: stored, sold, or misread

    def __post_init__(self):
        if self.count is None:
            self.count = self.start

    def set(self, count):
        """A new count. Potions are drunk one at a time, a few seconds apart; many gone in one
        reading were put away, sold or misread, so they aren't counted as drunk, and if they
        come back they cancel out rather than counting as bought."""
        if self.start is None:
            self.start = self.count = count
            return
        diff = count - self.count
        if diff < -BIG_DROP:
            self.removed -= diff
        elif diff < 0:
            self.used -= diff
        else:
            back = min(diff, self.removed)
            self.removed -= back
            self.added += diff - back
        self.count = count

    @property
    def cost(self):
        return self.used * self.price


class Session:
    """One tracked grind: EXP, mesos and potions from Start to Stop.

    Two clocks: grinding time stops counting when no EXP comes in for `idle_seconds` (in
    town, AFK) and while paused, so its rates are for time spent actually grinding; real time
    is every minute since Start except while paused, so its rates include the town trips."""

    def __init__(self, start_mesos=None, potions=(), idle_seconds=60, clock=time.time, exp_table=None):
        self.clock = clock
        self.started = clock()
        self.ended = None
        self.idle_seconds = idle_seconds
        self.exp = ExpTracker(exp_table)
        self.exp_gained = 0
        self.mesos_start = start_mesos          # None until the inventory has been seen
        self.mesos = start_mesos
        self.mesos_seen = self.started if start_mesos is not None else None
        self.potions = {p.name: p for p in potions}
        self.paused = False
        self._active = 0.0                  # active seconds up to self._anchor
        self._anchor = self.started
        self._events = deque()              # (active seconds when it happened, EXP gained)
        self._paused_for = 0.0                # seconds spent paused, before the current pause
        self._paused_at = None

    # ---- time
    def active(self, now=None):
        if self.paused or self.ended:
            return self._active
        now = self.clock() if now is None else now
        return self._active + min(max(0.0, now - self._anchor), self.idle_seconds)

    def idle(self, now=None):
        now = self.clock() if now is None else now
        return not self.paused and not self.ended and now - self._anchor > self.idle_seconds

    def _close(self, now):
        self._active = self.active(now)
        self._anchor = now

    def real(self, now=None):
        """Real time since Start, less any time paused."""
        end = self.ended or (self.clock() if now is None else now)
        paused = self._paused_for + (end - self._paused_at if self._paused_at is not None else 0)
        return max(0.0, end - self.started - paused)

    def pause(self, now=None):
        if not self.paused and not self.ended:
            now = self.clock() if now is None else now
            self._close(now)
            self.paused = True
            self._paused_at = now

    def resume(self, now=None):
        if self.paused and not self.ended:
            now = self.clock() if now is None else now
            self.paused = False
            self._anchor = now
            self._paused_for += now - self._paused_at
            self._paused_at = None

    # ---- readings
    def on_exp(self, exp, pct, now=None):
        now = self.clock() if now is None else now
        gain = self.exp.update(exp, pct)
        if gain and not self.paused and not self.ended:
            self._close(now)
            self.exp_gained += gain
            self._events.append((self._active, gain))
            while self._events and self._active - self._events[0][0] > ROLLING_SECONDS:
                self._events.popleft()
        return gain

    def set_mesos(self, mesos, now=None):
        if self.mesos_start is None:
            self.mesos_start = mesos
        self.mesos = mesos
        self.mesos_seen = self.clock() if now is None else now

    def set_potion(self, name, count):
        if name in self.potions:
            self.potions[name].set(count)

    def finish(self, mesos, counts, now=None):
        now = self.clock() if now is None else now
        self.set_mesos(mesos, now)
        for name, count in counts.items():
            self.set_potion(name, count)
        if not self.paused:
            self._close(now)
        self.ended = now

    # ---- results
    @staticmethod
    def _per_hour(amount, seconds):
        return amount / seconds * 3600 if seconds >= 10 else None

    def exp_rate(self, now=None):
        return self._per_hour(self.exp_gained, self.active(now))

    def recent_exp(self, now=None):
        """EXP gained in the last 5 minutes of grinding."""
        a = self.active(now)
        return sum(g for t, g in self._events if a - t <= ROLLING_SECONDS)

    def rolling_rate(self, now=None):
        a = self.active(now)
        gained = sum(g for t, g in self._events if a - t <= ROLLING_SECONDS)
        return self._per_hour(gained, min(a, ROLLING_SECONDS))

    def pct_rate(self, now=None):
        rate, needed = self.exp_rate(now), self.exp.needed()
        return rate / needed * 100 if rate is not None and needed else None

    def tnl_seconds(self, now=None):
        remaining = self.exp.remaining()
        rate = self.rolling_rate(now) or self.exp_rate(now)
        if remaining is None or not rate or rate <= 0:
            return None
        return remaining / rate * 3600

    @property
    def mesos_delta(self):
        return 0 if self.mesos_start is None else self.mesos - self.mesos_start

    @property
    def potion_cost(self):
        return sum(p.cost for p in self.potions.values())

    @property
    def net_mesos(self):
        """Mesos gained, counting potions as what they cost: drinking them is a loss, and
        buying more mid-session isn't (the mesos turned into potions you still have)."""
        return self.mesos_delta + sum(p.price * (p.count - p.start) for p in self.potions.values()
                                      if p.start is not None)

    def net_rate(self, now=None):
        return self._per_hour(self.net_mesos, self.active(now))

    # The same, over real time.
    def exp_rate_real(self, now=None):
        return self._per_hour(self.exp_gained, self.real(now))

    def pct_rate_real(self, now=None):
        rate, needed = self.exp_rate_real(now), self.exp.needed()
        return rate / needed * 100 if rate is not None and needed else None

    def net_rate_real(self, now=None):
        return self._per_hour(self.net_mesos, self.real(now))

    def summary(self, now=None):
        now = self.clock() if now is None else now
        level = self.exp.level()
        return {
            "started": self.started,
            "ended": self.ended,
            "total_seconds": round((self.ended or now) - self.started),
            "active_seconds": round(self.active(now)),
            "real_seconds": round(self.real(now)),
            "exp_gained": self.exp_gained,
            "levels": self.exp.levels,
            "level_start": level - self.exp.levels if level else None,
            "level_end": level,
            "exp_per_hour": self.exp_rate(now),
            "exp_per_hour_real": self.exp_rate_real(now),
            "pct_per_hour": self.pct_rate(now),
            "pct_per_hour_real": self.pct_rate_real(now),
            "mesos_start": self.mesos_start,
            "mesos_end": self.mesos,
            "mesos_delta": self.mesos_delta,
            "potions": [{"name": p.name, "price": p.price, "start": p.start, "end": p.count,
                         "used": p.used, "added": p.added, "removed": p.removed, "cost": p.cost}
                        for p in self.potions.values()],
            "potion_cost": self.potion_cost,
            "net_mesos": self.net_mesos,
            "net_per_hour": self.net_rate(now),
            "net_per_hour_real": self.net_rate_real(now),
        }
