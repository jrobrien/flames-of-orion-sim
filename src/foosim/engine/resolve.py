"""Action resolution - the core of the engine.

``apply(state, action, rules) -> (new_state, [Event])`` is a pure function: it
deep-copies ``state``, runs the RNG stream forward from ``state.rng_state``,
executes exactly one action against the copy, and returns it with the event log.

Resolution order follows RULES.md section 6. M3 covers the core loop
(Move / Ranged / Melee / Disengage / Purge, HEAT, overheat, catastrophic,
Explode); weapon/upgrade/ammo "special" behaviours are marked ``TODO(m7)``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from foosim.engine import hexgrid, legal
from foosim.engine.actions import (
    DisengageAction,
    IllegalAction,
    MeleeAttackAction,
    MoveAction,
    PurgeHeatAction,
    RangedAttackAction,
    SelfDestructAction,
)
from foosim.engine.events import Event, emit
from foosim.engine.legal import is_engaged, move_budget
from foosim.engine.rng import Rng
from foosim.engine.state import GameState, Unit, WeaponInstance
from foosim.engine.visibility import VisibilityConfig, line_of_sight

__all__ = ["AttackPlan", "apply", "blast_preview", "plan_attack"]

_BLAST_CFG = VisibilityConfig(mode="strict_center")
_RAIL_SELF_HEAT = 1  # `self_heat_1_on_use` - Rail Weapon heats its own firer


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------


def apply(state: GameState, action, rules) -> tuple[GameState, list[Event]]:
    s = state.copy()
    ev: list[Event] = []
    rng = Rng(state=s.rng_state)
    _apply_action(s, action, rules, rng, ev)
    s.rng_state = rng.state
    return s, ev


def _apply_action(s: GameState, action, rules, rng: Rng, ev: list[Event]) -> None:
    if isinstance(action, MoveAction):
        _do_move(s, action, rules, rng, ev)
    elif isinstance(action, RangedAttackAction):
        _do_ranged(s, action, rules, rng, ev)
    elif isinstance(action, MeleeAttackAction):
        _do_melee(s, action, rules, rng, ev)
    elif isinstance(action, DisengageAction):
        _do_disengage(s, action, rules, rng, ev)
    elif isinstance(action, PurgeHeatAction):
        _do_purge(s, action, rules, rng, ev)
    elif isinstance(action, SelfDestructAction):
        _do_self_destruct(s, action, rules, rng, ev)
    else:
        raise IllegalAction(f"not an executable action: {type(action).__name__}")


# --------------------------------------------------------------------------
# movement
# --------------------------------------------------------------------------


def _validate_and_move(s, u, path, *, budget, ev, kind) -> None:
    if not path or path[0] != u.pos:
        raise IllegalAction("path must start at the unit's position")
    flying = u.ignores_terrain_on_move
    total = 0.0
    for prev, nxt in zip(path[:-1], path[1:], strict=True):
        if hexgrid.distance(prev, nxt) != 1:
            raise IllegalAction("non-adjacent step in path")
        if not s.mapspec.in_bounds(nxt):
            raise IllegalAction("path leaves the board")
        occ = s.unit_at(nxt)
        if occ and occ.id != u.id and occ.side != u.side:
            raise IllegalAction("path crosses an enemy")
        if flying:
            total += 1.0
        else:
            hp, hn = s.column_height(prev), s.column_height(nxt)
            if abs(hn - hp) > legal.MAX_STEP_CLIMB:
                raise IllegalAction(f'step of {abs(hn - hp):.1f}" is too steep (max 2")')
            total += legal.step_cost(hp, hn)
    if total > budget + 1e-9:
        raise IllegalAction(f"path costs {total:.1f}, budget {budget}")
    dest = path[-1]
    occ = s.unit_at(dest)
    if occ and occ.id != u.id:
        raise IllegalAction("destination hex is occupied")
    u.pos = dest
    if kind == "move":
        u.statuses["moved_this_turn"] = 1
    emit(
        s, ev, "move",
        unit=u.id, to=[dest.q, dest.r],
        path=[[h.q, h.r] for h in path], cost=round(total, 2), kind=kind,
    )


def _do_move(s, a: MoveAction, rules, rng, ev) -> None:
    u = s.units[a.unit_id]
    if is_engaged(s, u):
        raise IllegalAction("engaged units must Disengage, not Move")
    budget = move_budget(u)
    if a.bolster == "run":
        budget += rules.inches_to_hexes(3)
    elif a.bolster not in (None, "charge", "snap_shot"):
        raise IllegalAction(f"unknown Move bolster: {a.bolster}")
    _validate_and_move(s, u, a.path, budget=budget, ev=ev, kind="move")
    if a.bolster == "charge" and a.melee_target is not None:
        mi = a.melee_weapon_index
        if mi is None:
            mi = next((j for j, w in enumerate(u.weapons) if w.kind == "melee"), None)
        if mi is not None:
            _do_melee(s, MeleeAttackAction(u.id, a.melee_target, mi), rules, rng, ev)
    elif a.bolster == "snap_shot" and a.shot_target is not None:
        _snap_shot(s, u, a, rules, rng, ev)


def _snap_shot(s, u, a: MoveAction, rules, rng, ev) -> None:
    t = s.units.get(a.shot_target)
    if t is None or t.out_of_action:
        return
    wi = a.shot_weapon_index
    if wi is None:
        wi = next(
            (j for j, w in enumerate(u.weapons)
             if w.kind == "ranged" and not w.used_this_turn and not w.disabled),
            None,
        )
    if wi is None:
        return
    shot_at = a.shot_at if 0 <= a.shot_at < len(a.path) else len(a.path) - 1
    dest = u.pos
    u.pos = a.path[shot_at]  # fire from the pause point
    w = u.weapons[wi]
    wspec = rules.weapon(w.weapon_id)
    tn, cover, long_range, reason = _effective_to_hit(
        s, u, t, wspec, rules, kind="ranged", bolster="snap_shot"
    )
    emit(s, ev, "snap_shot", unit=u.id, target=t.id, from_hex=[u.pos.q, u.pos.r])
    if reason is None:
        _resolve_attack(s, u, t, w, wspec, rules, rng, ev, tn=tn, cover=cover, kind="ranged",
                        long_range=long_range)
    u.pos = dest  # complete the movement


# --------------------------------------------------------------------------
# attacks
# --------------------------------------------------------------------------


def _indices_for(u, a, kind: str, all_flag: bool) -> list[int]:
    if all_flag:
        return [
            i for i, w in enumerate(u.weapons)
            if w.kind == kind and not w.used_this_turn and not w.disabled
        ]
    i = a.weapon_index
    if i is None or i < 0 or i >= len(u.weapons):
        raise IllegalAction("bad weapon index")
    w = u.weapons[i]
    if w.kind != kind:
        raise IllegalAction(f"weapon {i} is not {kind}")
    if w.used_this_turn:
        raise IllegalAction("weapon already used this turn")
    if w.disabled:
        raise IllegalAction("weapon is disabled")
    return [i]


_VIS_CFG: dict[str, VisibilityConfig] = {}


def _vis_cfg(rules) -> VisibilityConfig:
    key = rules.content_hash
    cfg = _VIS_CFG.get(key)
    if cfg is None:
        cfg = VisibilityConfig.from_rules(rules.raw)
        _VIS_CFG[key] = cfg
    return cfg


def _effective_to_hit(state, u, t, wspec, rules, *, kind: str, bolster: str | None,
                      los_cache: dict | None = None):
    """The to-hit target number (before Position Compromised, which is consumed in
    ``_resolve_attack``), plus cover / long-range flags. Returns
    ``(tn, cover, long_range, reason)`` where ``reason`` is a string if the attack
    is geometrically illegal. Shared by the resolver and :func:`plan_attack`.

    ``los_cache`` (optional ``dict`` keyed by ``(from_hex, to_hex)``) lets a caller
    that evaluates many variants of the same shot skip re-tracing LOS."""
    th = rules.to_hit
    specials = set(wspec.get("special", []))
    tn = u.stat("cs")
    cover = long_range = False
    dist = hexgrid.distance(u.pos, t.pos)
    if kind == "ranged":
        mr = wspec.get("max_range_inches")
        if mr is not None and dist > rules.inches_to_hexes(mr):
            return tn, cover, long_range, "target out of weapon range"
        if los_cache is not None and (u.pos, t.pos) in los_cache:
            los = los_cache[(u.pos, t.pos)]
        else:
            los = line_of_sight(state, u.pos, t.pos, _vis_cfg(rules))
            if los_cache is not None:
                los_cache[(u.pos, t.pos)] = los
        if "ignores_los" not in specials and not los.los:
            return tn, cover, long_range, "no line of sight to target"
        cover = bool(los.cover) and "ignores_cover" not in specials
        long_range = dist > rules.inches_to_hexes(th["long_range_inches"])
        ignores_lr = (
            "ignores_long_range_penalty" in specials or "long_range_targeting" in u.upgrades
        )
        if long_range and not ignores_lr:
            tn += th["long_range_cs_penalty"]
        if bolster == "focused_fire":
            tn -= th["focused_cs_bonus"]
        elif bolster == "snap_shot":
            tn += th["snap_shot_cs_penalty"]
        if "thermal_imaging" in u.upgrades:
            ti = rules.upgrade("thermal_imaging")["effect"]
            if t.heat >= int(ti["hot_threshold"]):
                tn += int(ti["cs_delta_vs_hot_target"])  # -1 -> easier
        if t.statuses.get("active_camo"):
            tn += int(rules.upgrade("camouflage")["effect"]["enemy_ranged_cs_penalty"])
    else:  # melee
        reach = rules.inches_to_hexes(wspec.get("reach_inches", 1))
        if dist > reach:
            return tn, cover, long_range, "melee target out of reach"
        if bolster == "focused_strike":
            tn -= th["focused_cs_bonus"]
    return tn, cover, long_range, None


def _do_ranged(s, a: RangedAttackAction, rules, rng, ev) -> None:
    u = s.units[a.unit_id]
    if is_engaged(s, u):
        raise IllegalAction("engaged units cannot make ranged attacks")
    if a.bolster not in (None, "unleash_hell", "focused_fire"):
        raise IllegalAction(f"unknown Ranged bolster: {a.bolster}")
    t = s.units.get(a.target_id)
    if t is None or t.out_of_action:
        raise IllegalAction("invalid ranged target")
    for i in _indices_for(u, a, "ranged", a.bolster == "unleash_hell"):
        w = u.weapons[i]
        wspec = rules.weapon(w.weapon_id)
        if "line_attack" in set(wspec.get("special", [])):
            _resolve_rail(s, u, t, w, wspec, rules, rng, ev)
            if t.out_of_action:
                break
            continue
        tn, cover, long_range, reason = _effective_to_hit(
            s, u, t, wspec, rules, kind="ranged", bolster=a.bolster
        )
        if reason:
            raise IllegalAction(reason)
        _resolve_attack(s, u, t, w, wspec, rules, rng, ev, tn=tn, cover=cover, kind="ranged",
                        long_range=long_range)
        if t.out_of_action:
            break


def _resolve_rail(s, u, t_initial, weap: WeaponInstance, wspec, rules, rng, ev) -> None:
    """Rail Weapon (``line_attack``): one attack from the firer *through* the aim
    point, continuing until the shot leaves the board or meets indestructible
    terrain. Every model on the line - friend or foe (``hits_friendlies``) - and
    every destructible-terrain hex takes a hit. LOS is needed only to the initial
    target (``los_initial_target_only``); Long Range is checked per hit roll; the
    firer gains ``+1`` HEAT (``self_heat_1_on_use``)."""
    th = rules.to_hit
    specials = set(wspec.get("special", []))
    dist0 = hexgrid.distance(u.pos, t_initial.pos)
    mr = wspec.get("max_range_inches")
    if mr is not None and dist0 > rules.inches_to_hexes(mr):
        raise IllegalAction("target out of weapon range")
    los0 = line_of_sight(s, u.pos, t_initial.pos, _vis_cfg(rules))
    if not los0.los:
        raise IllegalAction("no line of sight to target")

    # extend the sightline past the aim point along the same ray
    fx, fy = hexgrid.to_pixel(u.pos)
    tx, ty = hexgrid.to_pixel(t_initial.pos)
    vx, vy = tx - fx, ty - fy
    reach = 100.0 / (math.hypot(vx, vy) or 1.0)
    far = hexgrid.from_pixel(fx + vx * reach, fy + vy * reach)
    lane: list = []
    for h in hexgrid.line(u.pos, far)[1:]:
        if not s.mapspec.in_bounds(h):
            break
        lane.append(h)
    if t_initial.pos not in lane:  # hex rounding fell off the ray - use the direct segment
        lane = [h for h in hexgrid.line(u.pos, t_initial.pos)[1:] if s.mapspec.in_bounds(h)]

    weap.used_this_turn = True
    emit(s, ev, "rail_shot", unit=u.id, weapon=weap.weapon_id,
         aim=[t_initial.pos.q, t_initial.pos.r], path=[[h.q, h.r] for h in lane])
    ignores_lr = (
        "ignores_long_range_penalty" in specials or "long_range_targeting" in u.upgrades
    )
    for h in lane:
        terr = s.terrain.get(h)
        solid = terr is not None and not terr.destroyed
        if solid and "indestructible" in terr.tags:  # blocked_by_indestructible
            emit(s, ev, "rail_blocked", unit=u.id, pos=[h.q, h.r])
            break
        occ = s.unit_at(h)
        if occ is not None and not occ.out_of_action:
            is_initial = occ.id == t_initial.id
            cover = bool(los0.cover) if is_initial else False
            d = hexgrid.distance(u.pos, occ.pos)
            lr = d > rules.inches_to_hexes(th["long_range_inches"])
            tn = u.stat("cs") + (th["long_range_cs_penalty"] if (lr and not ignores_lr) else 0)
            _resolve_attack(s, u, occ, weap, wspec, rules, rng, ev,
                            tn=tn, cover=cover, kind="ranged", long_range=lr)
        if solid and "destructible" in terr.tags and "indestructible" not in terr.tags:
            _raze_terrain(s, h, ev, rules, rng, source=u.id)
    # +1 HEAT once the slug is downrange (may itself overheat the firer)
    _gain_heat(s, u, _RAIL_SELF_HEAT, "rail_weapon", ev, rng, rules)


def _do_melee(s, a: MeleeAttackAction, rules, rng, ev) -> None:
    u = s.units[a.unit_id]
    t = s.units.get(a.target_id)
    if t is None or t.out_of_action:
        raise IllegalAction("invalid melee target")
    if a.bolster not in (None, "fury", "focused_strike", "ram"):
        raise IllegalAction(f"unknown Melee bolster: {a.bolster}")

    if a.bolster == "ram":
        if not u.can_ram:
            raise IllegalAction("this unit cannot Ram")
        if hexgrid.distance(u.pos, t.pos) > 1:
            raise IllegalAction("Ram target must be within 1")
        self_d = rng.roll("1d3")
        tgt_d = rng.roll("1d3")
        emit(s, ev, "dice_roll", unit=u.id, purpose="ram_self", notation="1d3",
             results=[self_d], total=self_d)
        emit(s, ev, "dice_roll", unit=u.id, purpose="ram_target", notation="1d3",
             results=[tgt_d], total=tgt_d)
        _apply_damage(s, u, self_d, ap=0, cover=False, rules=rules, rng=rng, ev=ev, source=u.id,
                      weapon="ram", cause="ram")
        if not u.out_of_action:
            _apply_damage(s, t, tgt_d, ap=0, cover=False, rules=rules, rng=rng, ev=ev,
                          source=u.id, weapon="ram", cause="ram")
        return

    for i in _indices_for(u, a, "melee", a.bolster == "fury"):
        w = u.weapons[i]
        wspec = rules.weapon(w.weapon_id)
        tn, cover, long_range, reason = _effective_to_hit(
            s, u, t, wspec, rules, kind="melee", bolster=a.bolster
        )
        if reason:
            raise IllegalAction(reason)
        _resolve_attack(s, u, t, w, wspec, rules, rng, ev, tn=tn, cover=cover, kind="melee",
                        long_range=long_range)
        if t.out_of_action:
            break


def _resolve_attack(s, u, t, weap: WeaponInstance, wspec, rules, rng, ev, *,
                    tn: int, cover: bool, kind: str, long_range: bool,
                    widx: int | None = None) -> None:
    th = rules.to_hit
    specials = set(wspec.get("special", []))
    ammo_specials = (
        set(rules.ammo_spec(weap.ammo_id).get("special", [])) if weap.ammo_id else set()
    )
    pc = bool(t.statuses.get("position_compromised"))
    if pc:
        tn -= 1
    crit_on = 5 if "crit_on_5plus" in specials else th["always_crit_roll"]
    roll = rng.d6()
    emit(s, ev, "dice_roll", unit=u.id, purpose="to_hit", notation="d6", results=[roll], total=roll)
    if roll == th["always_miss_roll"]:
        outcome = "miss"
    elif roll >= crit_on:
        outcome = "crit"
    elif roll >= tn:
        outcome = "hit"
    else:
        outcome = "miss"
    if widx is None:  # identity, not ==: two identical weapons compare equal
        widx = next((i for i, w in enumerate(u.weapons) if w is weap), -1)
    emit(s, ev, "attack", attacker=u.id, target=t.id, weapon=weap.weapon_id, kind=kind,
         weapon_index=widx, ammo=weap.ammo_id,
         effective_cs=tn, roll=roll, outcome=outcome, cover=cover, long_range=long_range,
         position_compromised=pc)
    weap.used_this_turn = True
    if "half_speed_if_fired" in specials:
        u.statuses["heavy_fired"] = 1
    if pc:
        t.statuses.pop("position_compromised", None)
        emit(s, ev, "status_cleared", unit=t.id, status="position_compromised")
    if outcome == "miss":
        return

    if "target_heat_1d2_on_hit" in specials:  # Flame Thrower, before saves (FAQ)
        hn = rng.roll("1d2")
        emit(s, ev, "dice_roll", unit=u.id, purpose="flame_heat", notation="1d2",
             results=[hn], total=hn)
        _gain_heat(s, t, hn, "flame", ev, rng, rules)
        if t.out_of_action:
            return

    crit = outcome == "crit"
    dmg = rng.roll(str(wspec["damage"]))
    emit(s, ev, "dice_roll", unit=u.id, purpose="damage_dice", notation=str(wspec["damage"]),
         results=[dmg], total=dmg)
    if "plus1_damage" in ammo_specials:  # Hellfire Rounds
        dmg += 1
    lance_charge = _lance_charge(specials, u)
    if lance_charge:
        dmg += 2
    if crit:
        bonus = th["crit_bonus_damage"] + (1 if "sensor_array" in u.upgrades else 0)
        dmg += bonus
        emit(s, ev, "critical", attacker=u.id, target=t.id, bonus_damage=bonus)
        confirm = rng.d6()
        emit(s, ev, "dice_roll", unit=u.id, purpose="catastrophic_confirm", notation="d6",
             results=[confirm], total=confirm)
        if confirm >= u.stat("cs"):
            tr = rng.d6() + rng.d6()
            emit(s, ev, "dice_roll", unit=u.id, purpose="catastrophic_table", notation="2d6",
                 results=[tr], total=tr)
            cat = rules.catastrophic(tr)
            extra = _apply_catastrophic(s, t, cat, rules, rng, ev)
            dmg += th["catastrophic_bonus_damage"] + extra
            emit(s, ev, "catastrophic", target=t.id, confirm_roll=confirm, table_roll=tr,
                 result_name=cat["name"], effect=cat["effect"])

    if t.hp <= 0:  # e.g. Cockpit Fire
        _explode_check(s, t, rng, rules, ev, cause="catastrophic", credited_to=u.id)
        return

    ap = _ap_for(weap, wspec, t, rules) + (1 if lance_charge else 0)
    _apply_damage(s, t, dmg, ap=ap, cover=cover, rules=rules, rng=rng, ev=ev, source=u.id,
                  weapon=weap.weapon_id, cause="weapon")


def _lance_charge(specials: set, u: Unit) -> bool:
    return "plus2_damage_and_ap_if_moved" in specials and bool(u.statuses.get("moved_this_turn"))


def _ap_for(weap: WeaponInstance, wspec: dict, target: Unit, rules) -> int:
    ammo_specials = rules.ammo_spec(weap.ammo_id).get("special", []) if weap.ammo_id else []
    ap = 0
    if "armor_penetration" in set(wspec.get("special", [])):
        ap += 1
    if "armor_penetration" in set(ammo_specials):
        ap += 1
    return ap + target.modifiers.get("incoming_ap", 0)


# --------------------------------------------------------------------------
# pre-roll preview  (pure; no RNG, no mutation - the UI's shot planner)
# --------------------------------------------------------------------------


@dataclass
class AttackPlan:
    legal: bool
    reason: str | None
    kind: str
    weapon_id: str
    effective_cs: int          # displayed to-hit number (Position Compromised folded in)
    cover: bool
    long_range: bool
    position_compromised: bool
    hit_chance: float          # P(hit or crit)
    crit_chance: float         # P(natural 6)
    catastrophic_chance: float
    save_tn: int
    ap: int
    damage_expr: str
    expected_damage_through: float
    heat_cost: int             # activation HEAT this action would add


def _expected_roll(expr: str) -> float:
    e = str(expr).strip().lower()
    if e.isdigit():
        return float(e)
    m = re.fullmatch(r"(\d*)d(\d+)", e)
    if not m:
        return 0.0
    return int(m.group(1) or "1") * (int(m.group(2)) + 1) / 2.0


def _hit_chance(tn: int, th: dict) -> float:
    miss, crit = th["always_miss_roll"], th["always_crit_roll"]
    return sum(1 for r in range(1, 7) if r == crit or (r != miss and r >= tn)) / 6.0


def plan_attack(state, attacker_id: str, target_id: str, weapon_index: int, rules, *,
                kind: str, bolster: str | None = None,
                los_cache: dict | None = None) -> AttackPlan:
    """What a Ranged/Melee attack would look like, without rolling. Uses the same
    modifier logic as the resolver (:func:`_effective_to_hit`, :func:`_ap_for`).
    Pass a shared ``los_cache`` dict when scoring many variants of one shot."""
    th = rules.to_hit
    u = state.units[attacker_id]
    t = state.units.get(target_id)
    hr = rules.heat
    heat_cost = hr["second_action"] if state.actions_taken >= 1 else 0
    heat_cost += hr["per_bolstered_action"] if (bolster and bolster != "reboot") else 0

    def _fail(reason: str, tn: int = 0, cover: bool = False, lr: bool = False,
              pc: bool = False, expr: str = "0") -> AttackPlan:
        return AttackPlan(False, reason, kind, "", tn or u.stat("cs"), cover, lr, pc,
                          0.0, 0.0, 0.0, 0, 0, expr, 0.0, heat_cost)

    if weapon_index is None or weapon_index < 0 or weapon_index >= len(u.weapons):
        return _fail("no such weapon")
    weap = u.weapons[weapon_index]
    wspec = rules.weapon(weap.weapon_id)
    expr = str(wspec["damage"])
    if t is None or t.out_of_action:
        return _fail("invalid target", expr=expr)
    if weap.kind != kind:
        return _fail(f"weapon is not {kind}", expr=expr)
    if weap.used_this_turn:
        return _fail("weapon already used this turn", expr=expr)
    if weap.disabled:
        return _fail("weapon disabled", expr=expr)
    if kind == "ranged" and is_engaged(state, u):
        return _fail("attacker is engaged", expr=expr)

    tn, cover, long_range, reason = _effective_to_hit(
        state, u, t, wspec, rules, kind=kind, bolster=bolster, los_cache=los_cache
    )
    pc = bool(t.statuses.get("position_compromised"))
    disp_tn = tn - (1 if pc else 0)
    if reason is not None:
        return _fail(reason, tn=disp_tn, cover=cover, lr=long_range, pc=pc, expr=expr)

    specials = set(wspec.get("special", []))
    ammo_specials = set(rules.ammo_spec(weap.ammo_id).get("special", [])) if weap.ammo_id else set()
    crit_on = 5 if "crit_on_5plus" in specials else th["always_crit_roll"]
    lance_charge = _lance_charge(specials, u)

    hit_p = _hit_chance(disp_tn, th)
    crit_p = (7 - crit_on) / 6.0
    confirm_p = sum(1 for r in range(1, 7) if r >= u.stat("cs")) / 6.0
    ap = _ap_for(weap, wspec, t, rules) + (1 if lance_charge else 0)
    save_tn = t.stat("ar") - (th["cover_ar_bonus"] if cover else 0) + ap  # see _apply_damage
    save_p = sum(1 for r in range(1, 7) if r >= save_tn or r == th["ar_always_saves_on"]) / 6.0
    e_base = _expected_roll(expr)
    e_base += (1 if "plus1_damage" in ammo_specials else 0) + (2 if lance_charge else 0)
    crit_bonus = th["crit_bonus_damage"] + (1 if "sensor_array" in u.upgrades else 0)
    p_hit_noncrit = max(0.0, hit_p - crit_p)
    e_through = ((p_hit_noncrit * e_base) + (crit_p * (e_base + crit_bonus))) * (1.0 - save_p)
    return AttackPlan(
        legal=True, reason=None, kind=kind, weapon_id=weap.weapon_id,
        effective_cs=disp_tn, cover=cover, long_range=long_range, position_compromised=pc,
        hit_chance=hit_p, crit_chance=crit_p, catastrophic_chance=crit_p * confirm_p,
        save_tn=save_tn, ap=ap, damage_expr=expr,
        expected_damage_through=e_through, heat_cost=heat_cost,
    )


# --------------------------------------------------------------------------
# disengage / purge
# --------------------------------------------------------------------------


def _do_disengage(s, a: DisengageAction, rules, rng, ev) -> None:
    u = s.units[a.unit_id]
    if a.bolster not in (None, "dodge"):
        raise IllegalAction(f"unknown Disengage bolster: {a.bolster}")
    start = u.pos
    engaged_enemies = [
        e for e in s.units.values()
        if e.side != u.side and not e.out_of_action and hexgrid.distance(e.pos, start) <= 1
    ]
    _validate_and_move(s, u, a.path, budget=move_budget(u) // 2, ev=ev, kind="disengage")
    if a.bolster == "dodge":
        return
    for e in engaged_enemies:
        mi = next(
            (j for j, w in enumerate(e.weapons) if w.kind == "melee" and not w.disabled), None
        )
        if mi is None:
            continue
        mw = e.weapons[mi]
        wspec = rules.weapon(mw.weapon_id)
        emit(s, ev, "free_attack", attacker=e.id, target=u.id, reason="disengage")
        freebie = WeaponInstance(mw.weapon_id, "melee")  # reaction: does not consume e's weapon
        _resolve_attack(s, e, u, freebie, wspec, rules, rng, ev,
                        tn=e.stat("cs"), cover=False, kind="melee", long_range=False, widx=mi)
        if u.out_of_action:
            break


def _do_purge(s, a: PurgeHeatAction, rules, rng, ev) -> None:
    u = s.units[a.unit_id]
    if a.bolster not in (None, "reboot"):
        raise IllegalAction(f"unknown Purge bolster: {a.bolster}")
    if u.statuses.get("purged_this_turn"):
        raise IllegalAction("already purged this activation")
    ph = rules.raw["purge_heat"]
    if a.bolster == "reboot":
        if s.actions_taken != 0:
            raise IllegalAction("Reboot must be the unit's only action this turn")
        notation, mode = ph["reboot_dice"], "reboot"
    else:
        notation, mode = ph["dice"], "purge"
    amt = rng.roll(notation)
    emit(s, ev, "dice_roll", unit=u.id, purpose="purge", notation=notation,
         results=[amt], total=amt)
    removed = min(amt, u.heat)
    u.heat -= removed
    emit(s, ev, "heat_purge", unit=u.id, amount=removed, heat_after=u.heat, mode=mode)
    if mode == "purge":
        u.statuses["position_compromised"] = 1
        emit(s, ev, "status_applied", unit=u.id, status="position_compromised")
    u.statuses["purged_this_turn"] = 1


# --------------------------------------------------------------------------
# damage / heat / explode  (shared with engine.phases)
# --------------------------------------------------------------------------


_SAME = object()  # `dealer` default: the credited `source`


def _apply_damage(
    s, t: Unit, dmg: int, *, ap: int, cover: bool, rules, rng, ev, source,
    weapon: str | None = None, cause: str = "other", dealer=_SAME,
) -> None:
    """Resolve ``dmg`` against ``t``'s armor and emit the ``damage`` event.

    ``source`` is who gets *kill credit* (explosion chains credit the killer). The
    event also carries what analysis needs: ``dealer`` (the mech whose gear did it -
    the exploder for blasts), ``weapon`` (a weapon id, or the synthetic ``explosion`` /
    ``self_destruct`` / ``ram`` / ``terrain_collapse``), ``cause`` and ``friendly``
    (target on the dealer's own side). Friendly damage - notably a Rail Weapon's slug
    hitting teammates in its lane - is flagged here and left out of every damage-dealt
    metric (see ``sim.analyze``)."""
    if dmg <= 0 or t.out_of_action:
        return
    if dealer is _SAME:
        dealer = source
    if t.reactive_armor_left > 0:
        soak = min(t.reactive_armor_left, dmg)
        t.reactive_armor_left -= soak
        dmg -= soak
        emit(s, ev, "damage_soaked", target=t.id, amount=soak, source="reactive_armor")
        if dmg <= 0:
            return
    # QR p.61: cover is +1 to the AR *roll* (helps), AP is -1 to the AR *roll*
    # (hurts). Expressed as the natural roll needed: -cover, +ap. Natural 6 always
    # saves regardless of AP.
    save_tn = t.stat("ar") - (rules.to_hit["cover_ar_bonus"] if cover else 0) + ap
    always = rules.to_hit["ar_always_saves_on"]
    rolls = rng.pool(dmg)
    emit(s, ev, "dice_roll", unit=t.id, purpose="armor_save", notation=f"{dmg}d6",
         results=rolls, total=sum(rolls))
    through = sum(1 for r in rolls if not (r >= save_tn or r == always))
    emit(s, ev, "armor_save", target=t.id, save_tn=save_tn, rolls=rolls,
         ignored=dmg - through, through=through)
    if through > 0:
        before = t.hp
        t.hp = max(0, t.hp - through)
        d = s.units.get(dealer) if dealer else None
        emit(s, ev, "damage", target=t.id, amount=through, hp_before=before, hp_after=t.hp,
             source=source, dealer=dealer, weapon=weapon, cause=cause,
             friendly=d is not None and d.side == t.side)
    if t.hp <= 0:
        _explode_check(s, t, rng, rules, ev, cause="damage", credited_to=source)


def _gain_heat(s, u: Unit, amount: int, reason: str, ev, rng, rules) -> None:
    if amount == 0 or u.out_of_action:
        return
    u.heat += amount
    emit(s, ev, "heat_gain", unit=u.id, amount=amount, reason=reason, heat_after=u.heat)
    if u.heat >= u.stat("heat_limit"):
        emit(s, ev, "overheat", unit=u.id, heat=u.heat, heat_limit=u.stat("heat_limit"))
        _explode_check(s, u, rng, rules, ev, cause="overheat")


def _out_of_action(s, u: Unit, ev, *, cause: str) -> None:
    if u.out_of_action:
        return
    u.out_of_action = True
    u.hp = 0
    emit(s, ev, "out_of_action", unit=u.id, cause=cause)


def _explode_check(s, u: Unit, rng, rules, ev, *, cause: str, credited_to=None) -> None:
    if u.out_of_action:
        return
    u.hp = 0
    if not u.explodes:
        _out_of_action(s, u, ev, cause=cause)
        return
    roll = rng.d6()
    exploded = roll in rules.explode["explode_rolls"]
    emit(s, ev, "explode_check", unit=u.id, roll=roll, exploded=exploded)
    if not exploded:
        _out_of_action(s, u, ev, cause=cause)
        return

    _explode(s, u, rules, rng, ev, cause=cause, credited_to=credited_to, weapon="explosion")


def _blast(s, u: Unit, rules) -> tuple[int, int, list, list]:
    """(damage, radius_hexes, affected unit ids, razed terrain hexes) if ``u`` blew up
    now. Radius in inches equals current HEAT; a Nuclear Core counts as at least 10."""
    heat = max(0, u.heat)
    if "nuclear_core" in u.upgrades:
        heat = max(heat, int(rules.upgrade("nuclear_core")["effect"]["explode_as_heat"]))
    dmg = max(rules.explode["min_damage"], heat // rules.explode["damage_divisor"])
    radius = rules.inches_to_hexes(heat)
    affected = [
        o.id for o in s.units.values()
        if o.id != u.id and not o.out_of_action
        and hexgrid.distance(u.pos, o.pos) <= radius
        and line_of_sight(s, u.pos, o.pos, _BLAST_CFG).los
    ]
    # destructible terrain (low cover) in the blast is levelled
    razed = [
        h for h, t in s.terrain.items()
        if not t.destroyed and "destructible" in t.tags and "indestructible" not in t.tags
        and hexgrid.distance(u.pos, h) <= radius
        and line_of_sight(s, u.pos, h, _BLAST_CFG).los
    ]
    return dmg, radius, affected, razed


def blast_preview(state, unit: Unit, rules) -> tuple[int, int, list[str], list]:
    """Public, pure view of what ``unit`` exploding right now would do:
    ``(damage, radius_hexes, affected_unit_ids, razed_terrain_hexes)``. Used by bots
    deciding whether to Self Destruct."""
    return _blast(state, unit, rules)


def _explode(s, u: Unit, rules, rng, ev, *, cause: str, credited_to, weapon: str) -> None:
    """The blast itself. ``weapon`` names the synthetic weapon its damage is booked to:
    ``explosion`` (a mech dying and going up) or ``self_destruct`` (the upgrade) - kept
    separate so analysis can value them independently."""
    dmg, radius, affected, razed = _blast(s, u, rules)
    emit(s, ev, "explosion", unit=u.id, damage=dmg, radius=radius, affected=affected,
         terrain_razed=[[h.q, h.r] for h in razed], weapon=weapon)
    _out_of_action(s, u, ev, cause=cause)  # remove before chaining so it can't re-trigger
    for oid in affected:
        _apply_damage(s, s.units[oid], dmg, ap=0, cover=False, rules=rules, rng=rng, ev=ev,
                      source=credited_to or u.id, weapon=weapon, cause="explosion", dealer=u.id)
    for h in razed:
        _raze_terrain(s, h, ev, rules, rng, source=credited_to or u.id)


def _do_self_destruct(s, a: SelfDestructAction, rules, rng, ev) -> None:
    u = s.units[a.unit_id]
    if "self_destruct" not in u.upgrades:
        raise IllegalAction("unit has no Self Destruct upgrade")
    floor = int(rules.upgrade("self_destruct")["effect"]["self_destruct_min_heat"])
    if u.heat < floor:
        raise IllegalAction(f"Self Destruct needs {floor}+ HEAT")
    u.hp = 0
    emit(s, ev, "self_destruct", unit=u.id, heat=u.heat)
    _explode(s, u, rules, rng, ev, cause="self_destruct", credited_to=u.id,
             weapon="self_destruct")


def _raze_terrain(s, h, ev, rules, rng, *, source) -> None:
    t = s.terrain.get(h)
    if t is None or t.destroyed:
        return
    t.destroyed = True
    emit(s, ev, "terrain_destroyed", pos=[h.q, h.r])
    # RULES p.20: 1 damage to every model within 2" of the rubble
    for o in list(s.units.values()):
        if not o.out_of_action and hexgrid.distance(h, o.pos) <= rules.inches_to_hexes(2):
            _apply_damage(s, o, 1, ap=0, cover=False, rules=rules, rng=rng, ev=ev, source=source,
                          weapon="terrain_collapse", cause="terrain")


# --------------------------------------------------------------------------
# catastrophic table
# --------------------------------------------------------------------------


def _apply_catastrophic(s, t: Unit, cat: dict, rules, rng, ev) -> int:
    """Apply a catastrophic result's *effect* to ``t``; return extra damage."""
    extra = 0
    for token in (tok.strip() for tok in cat["effect"].split(";")):
        extra += _catastrophic_token(s, t, token, rules, rng, ev)
    return extra


def _catastrophic_token(s, t: Unit, token: str, rules, rng, ev) -> int:
    if token == "extra_damage_1d3":
        n = rng.roll("1d3")
        emit(s, ev, "dice_roll", unit=t.id, purpose="catastrophic_extra", notation="1d3",
             results=[n], total=n)
        return n
    if token == "extra_damage_1":
        return 1
    if token == "special_ammo_lost":
        for w in t.weapons:
            if w.ammo_id:
                emit(s, ev, "ammo_lost", unit=t.id, weapon=w.weapon_id, ammo=w.ammo_id)
                w.ammo_id = None
        return 0
    if token == "set_hp_0":
        t.hp = 0
        return 0
    if token in ("disable_random_weapon", "disable_random_platform"):
        live = [w for w in t.weapons if not w.disabled]
        if live:
            w = rng.choice(live)
            w.disabled = True
            emit(s, ev, "weapon_disabled", unit=t.id, weapon=w.weapon_id)
        return 0
    if token == "attackers_gain_ap":
        t.modifiers["incoming_ap"] = t.modifiers.get("incoming_ap", 0) + 1
        emit(s, ev, "modifier_applied", unit=t.id, stat="incoming_ap", delta=1,
             source="catastrophic")
        return 0
    if token == "damage_1_to_random_model_within_3in":
        near = [
            o for o in s.units.values()
            if not o.out_of_action and hexgrid.distance(t.pos, o.pos) <= rules.inches_to_hexes(3)
        ]
        if near:
            victim = rng.choice(near)
            emit(s, ev, "ricochet", target=victim.id, amount=1)
            _apply_damage(s, victim, 1, ap=0, cover=False, rules=rules, rng=rng, ev=ev,
                          source=t.id, weapon="ricochet", cause="catastrophic", dealer=None)
        return 0
    if ":" in token:
        stat, _, raw = token.partition(":")
        delta = int(raw)
        key = {"cs_delta": "cs", "speed_delta": "speed", "heat_limit_delta": "heat_limit"}.get(stat)
        if key:
            t.modifiers[key] = t.modifiers.get(key, 0) + delta
            emit(s, ev, "modifier_applied", unit=t.id, stat=key, delta=delta, source="catastrophic")
            return 0
    emit(s, ev, "unhandled_effect", unit=t.id, token=token)  # TODO(m7)
    return 0
