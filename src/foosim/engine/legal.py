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


def _usable(weapons, kind: str) -> list[int]:
    return [
        i for i, w in enumerate(weapons)
        if w.kind == kind and not w.used_this_turn and not w.disabled
    ]


def _ranged_can_hit(state, u, wspec, t, rules, cfg) -> bool:
    d = hexgrid.distance(u.pos, t.pos)
    mr = wspec.get("max_range_inches")
    if mr is not None and d > rules.inches_to_hexes(mr):
        return False
    if "ignores_los" in set(wspec.get("special", [])):
        return True
    return line_of_sight(state, u.pos, t.pos, cfg).los


def legal_actions(state, unit, rules, *, bolster: bool = True) -> list:
    """Every action ``unit`` may take now. With ``bolster`` (default), also lists
    the legal bolstered variants (run / charge / focused_fire / unleash_hell /
    focused_strike / fury / ram / dodge / reboot). ``snap_shot`` is omitted - the
    engine does not implement it yet."""
    u = unit
    acts: list = []
    engaged = is_engaged(state, u)
    speed = u.stat("speed")
    cfg = VisibilityConfig.from_rules(rules.raw)
    enemies = [t for t in state.units.values() if t.side != u.side and not t.out_of_action]
    melee_idx = _usable(u.weapons, "melee")

    # ---- movement ----
    if engaged:
        for path in move_paths(state, u, budget=speed // 2).values():
            acts.append(DisengageAction(u.id, path))
            if bolster:
                acts.append(DisengageAction(u.id, path, bolster="dodge"))
    else:
        base_paths = move_paths(state, u, budget=speed)
        for path in base_paths.values():
            acts.append(MoveAction(u.id, path))
        if bolster:
            run_budget = speed + rules.inches_to_hexes(3)
            for path in move_paths(state, u, budget=run_budget).values():
                acts.append(MoveAction(u.id, path, bolster="run"))
            if melee_idx:
                mi = melee_idx[0]
                for dest, path in base_paths.items():
                    e = next((x for x in enemies if hexgrid.distance(dest, x.pos) <= 1), None)
                    if e is not None:
                        acts.append(MoveAction(u.id, path, bolster="charge",
                                               melee_target=e.id, melee_weapon_index=mi))

    # ---- ranged ----
    if not engaged:
        ranged_idx = _usable(u.weapons, "ranged")
        can_hit: dict[tuple[int, str], bool] = {}
        for i in ranged_idx:
            wspec = rules.weapon(u.weapons[i].weapon_id)
            for t in enemies:
                if not _ranged_can_hit(state, u, wspec, t, rules, cfg):
                    continue
                can_hit[(i, t.id)] = True
                acts.append(RangedAttackAction(u.id, t.id, i))
                if bolster:
                    acts.append(RangedAttackAction(u.id, t.id, i, bolster="focused_fire"))
        if bolster and ranged_idx:
            for t in enemies:
                if all(can_hit.get((i, t.id)) for i in ranged_idx):
                    acts.append(
                        RangedAttackAction(u.id, t.id, ranged_idx[0], bolster="unleash_hell")
                    )

    # ---- melee ----
    can_melee: dict[tuple[int, str], bool] = {}
    for i in melee_idx:
        wspec = rules.weapon(u.weapons[i].weapon_id)
        reach = rules.inches_to_hexes(wspec.get("reach_inches", 1))
        for t in enemies:
            if hexgrid.distance(u.pos, t.pos) <= reach:
                can_melee[(i, t.id)] = True
                acts.append(MeleeAttackAction(u.id, t.id, i))
                if bolster:
                    acts.append(MeleeAttackAction(u.id, t.id, i, bolster="focused_strike"))
    if bolster and melee_idx:
        for t in enemies:
            if all(can_melee.get((i, t.id)) for i in melee_idx):
                acts.append(MeleeAttackAction(u.id, t.id, melee_idx[0], bolster="fury"))
    if bolster and u.can_ram:
        for t in enemies:
            if hexgrid.distance(u.pos, t.pos) <= 1:
                acts.append(MeleeAttackAction(u.id, t.id, melee_idx[0] if melee_idx else 0,
                                              bolster="ram"))

    # ---- purge ----
    if u.heat > 0 and not u.statuses.get("purged_this_turn"):
        acts.append(PurgeHeatAction(u.id))
        if bolster and state.actions_taken == 0:
            acts.append(PurgeHeatAction(u.id, bolster="reboot"))

    return acts
