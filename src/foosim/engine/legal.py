"""Legal-action enumeration + small spatial predicates. Pure, engine-only.

Used by ``ai/`` policies and (later) the UI to know what a unit may do. The
engine's ``resolve`` still validates independently - this is an affordance list,
not the authority.
"""

from __future__ import annotations

from foosim.engine import hexgrid
from foosim.engine.actions import (
    DisengageAction,
    MeleeAttackAction,
    MoveAction,
    PurgeHeatAction,
    RangedAttackAction,
)
from foosim.engine.hexgrid import Hex
from foosim.engine.visibility import VisibilityConfig, line_of_sight

__all__ = ["is_engaged", "legal_actions", "move_paths"]


def is_engaged(state, unit) -> bool:
    return any(
        e.side != unit.side
        and not e.out_of_action
        and hexgrid.distance(e.pos, unit.pos) <= 1
        for e in state.units.values()
    )


def _move_blockers(state, unit) -> set[Hex]:
    blocked: set[Hex] = set()
    if not unit.ignores_terrain_on_move:
        for h, t in state.terrain.items():
            if not t.destroyed and "blocking" in t.tags:
                blocked.add(h)
    for other in state.units.values():
        if other.id != unit.id and not other.out_of_action and other.side != unit.side:
            blocked.add(other.pos)
    return blocked


def move_paths(state, unit, *, budget: int) -> dict[Hex, list[Hex]]:
    """dest hex -> path (list of adjacent hexes, ``unit.pos`` first). May pass
    through friendly-occupied hexes but not end on any occupied hex."""
    start = unit.pos
    blocked = _move_blockers(state, unit)
    came: dict[Hex, Hex | None] = {start: None}
    dist = {start: 0}
    frontier = [start]
    while frontier:
        nxt: list[Hex] = []
        for h in frontier:
            if dist[h] >= budget:
                continue
            for nb in hexgrid.neighbors(h):
                if nb in came or nb in blocked or not state.mapspec.in_bounds(nb):
                    continue
                came[nb] = h
                dist[nb] = dist[h] + 1
                nxt.append(nb)
        frontier = nxt

    out: dict[Hex, list[Hex]] = {}
    for h in came:
        if h == start or state.unit_at(h) is not None:
            continue
        path = [h]
        p = came[h]
        while p is not None:
            path.append(p)
            p = came[p]
        out[h] = list(reversed(path))
    return out


def legal_actions(state, unit, rules) -> list:
    acts: list = []
    engaged = is_engaged(state, unit)
    speed = unit.stat("speed")

    if engaged:
        for path in move_paths(state, unit, budget=speed // 2).values():
            acts.append(DisengageAction(unit.id, path))
    else:
        for path in move_paths(state, unit, budget=speed).values():
            acts.append(MoveAction(unit.id, path))

    cfg = VisibilityConfig.from_rules(rules.raw)
    enemies = [t for t in state.units.values() if t.side != unit.side and not t.out_of_action]

    if not engaged:
        for i, w in enumerate(unit.weapons):
            if w.kind != "ranged" or w.used_this_turn or w.disabled:
                continue
            wspec = rules.weapon(w.weapon_id)
            specials = set(wspec.get("special", []))
            for t in enemies:
                d = hexgrid.distance(unit.pos, t.pos)
                mr = wspec.get("max_range_inches")
                if mr is not None and d > rules.inches_to_hexes(mr):
                    continue
                has_los = "ignores_los" in specials or line_of_sight(
                    state, unit.pos, t.pos, cfg
                ).los
                if not has_los:
                    continue
                acts.append(RangedAttackAction(unit.id, t.id, i))

    for i, w in enumerate(unit.weapons):
        if w.kind != "melee" or w.used_this_turn or w.disabled:
            continue
        wspec = rules.weapon(w.weapon_id)
        reach = rules.inches_to_hexes(wspec.get("reach_inches", 1))
        for t in enemies:
            if hexgrid.distance(unit.pos, t.pos) <= reach:
                acts.append(MeleeAttackAction(unit.id, t.id, i))

    if unit.heat > 0 and not unit.statuses.get("purged_this_turn"):
        acts.append(PurgeHeatAction(unit.id))

    return acts
