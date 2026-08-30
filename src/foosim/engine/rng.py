"""Deterministic PRNG + dice helpers for the Flames of Orion engine.

Uses splitmix64 so a given seed reproduces a game identically *across languages*
(a Python ``random`` stream would not survive a port to Godot / C#). Stdlib only.

``Rng.state`` is the entire serializable state: persist it on ``GameState`` and
rebuild with ``Rng(state=...)`` to resume mid-game.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["MASK64", "Rng"]

MASK64 = (1 << 64) - 1
_GAMMA = 0x9E3779B97F4A7C15
_MIX1 = 0xBF58476D1CE4E5B9
_MIX2 = 0x94D049BB133111EB
_DICE_RE = re.compile(r"\A(\d*)d(\d+)\Z")
_INT_RE = re.compile(r"\A(\d+)\Z")


def _mix(z: int) -> int:
    z = ((z ^ (z >> 30)) * _MIX1) & MASK64
    z = ((z ^ (z >> 27)) * _MIX2) & MASK64
    return z ^ (z >> 31)


@dataclass
class Rng:
    """A splitmix64 stream."""

    state: int

    @classmethod
    def from_seed(cls, seed: int) -> Rng:
        return cls(state=seed & MASK64)

    def _next_u64(self) -> int:
        self.state = (self.state + _GAMMA) & MASK64
        return _mix(self.state)

    # -- primitives -------------------------------------------------------
    def random(self) -> float:
        """Float in [0, 1) with 53 bits of precision."""
        return (self._next_u64() >> 11) / (1 << 53)

    def randint(self, lo: int, hi: int) -> int:
        """Uniform integer in [lo, hi] inclusive, unbiased (rejection sampling)."""
        span = hi - lo + 1
        if span <= 0:
            raise ValueError(f"empty range [{lo}, {hi}]")
        limit = (MASK64 + 1) - ((MASK64 + 1) % span)
        while True:
            x = self._next_u64()
            if x < limit:
                return lo + (x % span)

    def choice(self, seq):
        if not seq:
            raise IndexError("choice from empty sequence")
        return seq[self.randint(0, len(seq) - 1)]

    def shuffle(self, seq: list) -> None:
        """In-place Fisher-Yates shuffle."""
        for i in range(len(seq) - 1, 0, -1):
            j = self.randint(0, i)
            seq[i], seq[j] = seq[j], seq[i]

    def fork(self) -> Rng:
        """An independent stream derived from (and advancing) this one."""
        return Rng.from_seed(self._next_u64())

    # -- dice ------------------------------------------------------------
    def die(self, sides: int = 6) -> int:
        return self.randint(1, sides)

    def d6(self) -> int:
        return self.randint(1, 6)

    def d3(self) -> int:
        return self.randint(1, 3)

    def d2(self) -> int:
        return self.randint(1, 2)

    def ndn(self, n: int, sides: int = 6) -> list[int]:
        return [self.randint(1, sides) for _ in range(n)]

    def pool(self, count: int, sides: int = 6) -> list[int]:
        """A dice pool (e.g. one armor-save die per point of damage)."""
        return [self.randint(1, sides) for _ in range(count)]

    def d66(self) -> int:
        return self.randint(1, 6) * 10 + self.randint(1, 6)

    def roll(self, spec: str | int) -> int:
        """Evaluate a dice spec: ``"2d6"``, ``"d3"``, ``"1d2"``, or a plain ``"4"`` / ``4``."""
        if isinstance(spec, int):
            return spec
        s = spec.strip().lower()
        m = _INT_RE.match(s)
        if m:
            return int(m.group(1))
        m = _DICE_RE.match(s)
        if not m:
            raise ValueError(f"bad dice spec: {spec!r}")
        n = int(m.group(1) or "1")
        sides = int(m.group(2))
        if n < 1 or sides < 1:
            raise ValueError(f"bad dice spec: {spec!r}")
        return sum(self.randint(1, sides) for _ in range(n))

    # -- serialization -------------------------------------------------
    def to_dict(self) -> dict:
        return {"state": self.state}

    @classmethod
    def from_dict(cls, d: dict) -> Rng:
        return cls(state=int(d["state"]) & MASK64)
