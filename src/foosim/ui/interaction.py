"""Targeting helpers for interactive play. Pure - no imgui.

Given the current interaction mode and the activating unit, compute what the map
should highlight (reachable hexes / valid attack targets) and how a "bolster"
checkbox maps to a concrete sub-mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from foosim.engine import legal, resolve
from foosim.engine.hexgrid import Hex

__all__ = ["MODES", "Overlay", "compute_overlay", "submode"]

MODES = (
    "idle",
    "targeting_move",
    "targeting_disengage",
    "targeting_ranged",
    "targeting_melee",
)

# bolster checkbox -> concrete sub-mode, per interaction mode
_BOLSTER_SUBMODE = {
    "targeting_move": "run",
    "targeting_disengage": "dodge",
    "targeting_ranged": "focused_fire",
    "targeting_melee": "focused_strike",
}


def submode(mode: str, bolster: bool) -> str | None:
    return _BOLSTER_SUBMODE.get(mode) if bolster else None


@dataclass
class Overlay:
    mode: str
    reachable: dict[Hex, list[Hex]] = field(default_factory=dict)  # dest -> path
    targets: set[str] = field(default_factory=set)  # unit ids

    def is_valid_dest(self, h: Hex) -> bool:
        return h in self.reachable

    def is_valid_target_hex(self, state, h: Hex) -> str | None:
        u = state.unit_at(h)
        return u.id if (u is not None and u.id in self.targets) else None


def compute_overlay(
    state,
    rules,
    mode: str,
    unit_id: str | None,
    weapon_index: int | None,
    bolster: bool,
) -> Overlay:
    if not unit_id or unit_id not in state.units or mode not in MODES or mode == "idle":
        return Overlay("idle")
    u = state.units[unit_id]

    if mode == "targeting_move":
        budget = u.stat("speed") + (rules.inches_to_hexes(3) if bolster else 0)  # "run"
        return Overlay(mode, reachable=legal.move_paths(state, u, budget=budget))
    if mode == "targeting_disengage":
        return Overlay(mode, reachable=legal.move_paths(state, u, budget=u.stat("speed") // 2))

    kind = "ranged" if mode == "targeting_ranged" else "melee"
    sub = submode(mode, bolster)
    targets = {
        t.id
        for t in state.units.values()
        if t.side != u.side
        and not t.out_of_action
        and resolve.plan_attack(
            state, u.id, t.id, weapon_index, rules, kind=kind, bolster=sub
        ).legal
    }
    return Overlay(mode, targets=targets)
