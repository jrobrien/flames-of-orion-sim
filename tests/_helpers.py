"""Shared test helpers (importable because pytest puts tests/ on sys.path)."""

from __future__ import annotations

from foosim.engine.hexgrid import Hex
from foosim.engine.rng import Rng
from foosim.engine.state import GameState, MapSpec
from foosim.sim.setups import mech


def rng_state_for_rolls(prefix, limit: int = 500_000) -> int:
    """Smallest rng state whose first ``len(prefix)`` ``d6()`` draws equal ``prefix``."""
    want = list(prefix)
    n = len(want)
    for cand in range(limit):
        r = Rng(state=cand)
        if [r.d6() for _ in range(n)] == want:
            return cand
    raise AssertionError(f"no rng state produces d6 prefix {want}")


def duel(
    rules,
    *,
    a_pos: Hex | None = None,
    b_pos: Hex | None = None,
    a_ranged=("medium_weapon",),
    a_melee=("close_combat_weapon",),
    b_ranged=(),
    b_melee=(),
    rng_state: int = 0,
    a_over: dict | None = None,
    b_over: dict | None = None,
) -> GameState:
    a_pos = a_pos or Hex(0, 0)
    b_pos = b_pos or Hex(0, 2)
    a = mech(rules, id="A", side=0, name="A", pos=a_pos, ranged=a_ranged, melee=a_melee)
    b = mech(rules, id="B", side=1, name="B", pos=b_pos, ranged=b_ranged, melee=b_melee)
    for k, v in (a_over or {}).items():
        setattr(a, k, v)
    for k, v in (b_over or {}).items():
        setattr(b, k, v)
    return GameState(
        mapspec=MapSpec(cols=16, rows=16),
        units={"A": a, "B": b},
        initiative=(0, 1),
        pass_tokens={0: 0, 1: 0},
        rng_state=rng_state,
        phase="activation",
    )
