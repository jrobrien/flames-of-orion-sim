"""Targeting helpers for interactive play. Pure - no imgui.

Given the interaction mode, the chosen bolster sub-mode, and the activating unit,
compute what the map highlights: reachable hexes/paths (move / disengage) or
``plan_attack``-legal target ids (ranged / melee).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from foosim.engine import hexgrid, legal, resolve
from foosim.engine.hexgrid import Hex

__all__ = ["MODES", "SUBMODES", "SUBMODE_LABELS", "Overlay", "compute_overlay"]

MODES = (
    "idle",
    "targeting_move",
    "targeting_disengage",
    "targeting_ranged",
    "targeting_melee",
)

# "" == standard (no bolster). snap_shot is omitted (engine stub).
SUBMODES: dict[str, tuple[str, ...]] = {
    "targeting_move": ("", "run", "charge"),
    "targeting_disengage": ("", "dodge"),
    "targeting_ranged": ("", "focused_fire", "unleash_hell"),
    "targeting_melee": ("", "focused_strike", "fury", "ram"),
}

SUBMODE_LABELS = {
    "": "standard",
    "run": 'run (+3")',
    "charge": "charge (-> free melee)",
    "dodge": "dodge (no free hit)",
    "focused_fire": "focused fire (+1 CS)",
    "unleash_hell": "unleash hell (all ranged)",
    "focused_strike": "focused strike (+1 CS)",
    "fury": "fury (all melee)",
    "ram": "ram (1d3 self / 1d3 target, adjacent)",
}


@dataclass
class Overlay:
    mode: str
    reachable: dict[Hex, list[Hex]] = field(default_factory=dict)  # dest -> path
    targets: set[str] = field(default_factory=set)  # unit ids
    charge_targets: dict[Hex, str] = field(default_factory=dict)  # dest -> enemy id (charge only)

    def is_valid_dest(self, h: Hex) -> bool:
        return h in self.reachable


def _enemies(state, u):
    return [t for t in state.units.values() if t.side != u.side and not t.out_of_action]


def compute_overlay(
    state,
    rules,
    mode: str,
    unit_id: str | None,
    weapon_index: int | None,
    sub: str = "",
) -> Overlay:
    if not unit_id or unit_id not in state.units or mode not in MODES or mode == "idle":
        return Overlay("idle")
    u = state.units[unit_id]

    if mode == "targeting_move":
        budget = u.stat("speed") + (rules.inches_to_hexes(3) if sub == "run" else 0)
        reach = legal.move_paths(state, u, budget=budget)
        if sub == "charge":
            has_melee = any(
                w.kind == "melee" and not w.used_this_turn and not w.disabled for w in u.weapons
            )
            ct: dict[Hex, str] = {}
            if has_melee:
                for dest in reach:
                    e = next(
                        (x for x in _enemies(state, u) if hexgrid.distance(dest, x.pos) <= 1), None
                    )
                    if e is not None:
                        ct[dest] = e.id
            return Overlay(mode, reachable={d: reach[d] for d in ct}, charge_targets=ct)
        return Overlay(mode, reachable=reach)

    if mode == "targeting_disengage":
        return Overlay(mode, reachable=legal.move_paths(state, u, budget=u.stat("speed") // 2))

    # attack modes
    enemies = _enemies(state, u)
    kind = "ranged" if mode == "targeting_ranged" else "melee"

    if sub == "ram":
        if not u.can_ram:
            return Overlay(mode)
        return Overlay(mode, targets={t.id for t in enemies if hexgrid.distance(u.pos, t.pos) <= 1})

    if sub in ("unleash_hell", "fury"):
        idxs = [
            i for i, w in enumerate(u.weapons)
            if w.kind == kind and not w.used_this_turn and not w.disabled
        ]
        targets = {
            t.id for t in enemies
            if idxs and all(
                resolve.plan_attack(state, u.id, t.id, i, rules, kind=kind).legal for i in idxs
            )
        }
        return Overlay(mode, targets=targets)

    b = sub or None
    targets = {
        t.id for t in enemies
        if resolve.plan_attack(
            state, u.id, t.id, weapon_index, rules, kind=kind, bolster=b
        ).legal
    }
    return Overlay(mode, targets=targets)
