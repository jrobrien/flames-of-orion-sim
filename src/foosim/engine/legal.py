"""Legal-action enumeration + small spatial predicates. Pure, engine-only.

Used by ``ai/`` policies and (later) the UI to know what a unit may do. The
engine's ``resolve`` still validates independently - this is an affordance list,
not the authority.
"""

from __future__ import annotations

from heapq import heappop, heappush

from foosim.engine import hexgrid
from foosim.engine.actions import (
    DisengageAction,
    MeleeAttackAction,
    MoveAction,
    PurgeHeatAction,
    RangedAttackAction,
    SelfDestructAction,
)
from foosim.engine.hexgrid import Hex
from foosim.engine.visibility import VisibilityConfig, line_of_sight

__all__ = [
    "MAX_STEP_CLIMB", "is_engaged", "legal_actions", "move_budget", "move_paths", "step_cost",
]

# can't climb up / drop down more than 2" in one hex step (RULES: gaps > 2")
MAX_STEP_CLIMB = 2.0


def move_budget(unit) -> int:
    """Hexes this unit may move this activation (before run/disengage). Halved if
    it fired a Heavy Weapon this turn."""
    speed = unit.stat("speed")
    return speed // 2 if unit.statuses.get("heavy_fired") else speed


def is_engaged(state, unit) -> bool:
    return any(
        e.side != unit.side
        and not e.out_of_action
        and hexgrid.distance(e.pos, unit.pos) <= 1
        for e in state.units.values()
    )


def _enemy_hexes(state, unit) -> set[Hex]:
    return {
        o.pos for o in state.units.values()
        if o.id != unit.id and not o.out_of_action and o.side != unit.side
    }


def step_cost(prev_h: float, next_h: float) -> float:
    """Move cost to step onto an adjacent hex: 1 + the vertical climb (descending
    is free). Terrain is traversed *over* (roofs, hilltops), never through."""
    return 1.0 + max(0.0, next_h - prev_h)


def move_paths(state, unit, *, budget: float) -> dict[Hex, list[Hex]]:
    """dest hex -> path (adjacent hexes, ``unit.pos`` first). Dijkstra over the
    board: terrain is passable but climbing a building / hill costs its height;
    a step steeper than ``MAX_STEP_CLIMB`` is impossible (VTOL/aircraft ignore
    heights). May pass through friendly-occupied hexes, not end on any."""
    start = unit.pos
    flying = unit.ignores_terrain_on_move
    enemies = _enemy_hexes(state, unit)
    hcache: dict[Hex, float] = {}

    def h_at(h: Hex) -> float:
        if flying:
            return 0.0
        v = hcache.get(h)
        if v is None:
            v = state.column_height(h)
            hcache[h] = v
        return v

    best: dict[Hex, float] = {start: 0.0}
    came: dict[Hex, Hex | None] = {start: None}
    frontier: list[tuple[float, Hex]] = [(0.0, start)]
    while frontier:
        c, h = heappop(frontier)
        if c > best.get(h, 1e18):
            continue
        hh = h_at(h)
        for nb in hexgrid.neighbors(h):
            if nb in enemies or not state.mapspec.in_bounds(nb):
                continue
            nbh = h_at(nb)
            if not flying and abs(nbh - hh) > MAX_STEP_CLIMB:
                continue
            nc = c + (1.0 if flying else step_cost(hh, nbh))
            if nc <= budget + 1e-9 and nc < best.get(nb, 1e18):
                best[nb] = nc
                came[nb] = h
                heappush(frontier, (nc, nb))

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
    speed = move_budget(u)
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

    # ---- self destruct (upgrade) ----
    if "self_destruct" in u.upgrades:
        floor = int(rules.upgrade("self_destruct")["effect"]["self_destruct_min_heat"])
        if u.heat >= floor:
            acts.append(SelfDestructAction(u.id))

    return acts
