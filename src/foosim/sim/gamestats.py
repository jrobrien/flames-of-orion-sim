"""Per-mech and per-weapon results extracted from one finished game's event log.

The raw material for build / weapon analysis (see ``sim.store`` for the SQLite tables
and ``foosim-analyze schema`` for column meanings). One ``UnitRow`` per mech per game
describes its *build* (frame, final stats, gear, cost, perk) and what it *did*
(damage dealt by source, damage taken, kills, ...); one ``WeaponRow`` per weapon slot
carries that weapon's attacks / hits / crits / damage, plus rows for the synthetic
weapons ``explosion``, ``self_destruct``, ``ram`` and ``terrain_collapse``.

Damage accounting rules (these define the headline metrics):
  * damage dealt counts only hits on the *enemy* side. Friendly damage - a Rail
    Weapon's slug raking teammates, a blast catching a friend, ram self-damage - is
    recorded separately in ``friendly_damage`` and is left OUT of every damage-dealt
    metric (it is a side effect of a shot, not effectiveness).
  * weapon damage is booked to the weapon that fired (``cause == "weapon"``); a mech's
    death explosion and the Self Destruct upgrade are separate synthetic weapons so
    they can be valued independently; ram and terrain collapses are ``damage_other``.
  * a blast is credited to the mech that exploded, not to whoever killed it.
  * kills are credited to the source of the last damage that took the target out
    (approximate for catastrophic-only deaths).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from foosim.engine.rules import Ruleset
from foosim.engine.state import GameState, Unit

__all__ = ["UnitRow", "WeaponRow", "extract", "unit_cost"]

SYNTHETIC_WEAPONS = ("explosion", "self_destruct", "ram", "terrain_collapse")


def _d(doc: str, default=None):
    return field(default=default, metadata={"doc": doc})


@dataclass
class UnitRow:
    seed: int = _d("Game seed (with run_id identifies the game).", 0)
    unit_id: str = _d("Unit id in the game, e.g. A1 (side A, 1st mech).", "")
    side: int = _d("0 or 1.", 0)
    name: str = _d("Call sign.", "")
    frame: str = _d("light | medium | heavy (or the profile name).", "")
    leader: int = _d("1 if this mech is its squad leader (has a perk).", 0)
    perk: str = _d("Experience perk id, '' if none.", "")
    hp_max: int = _d("Starting hull points (upgrades included).", 0)
    ar: int = _d("Armor target number (save on AR+).", 0)
    cs: int = _d("Combat skill target number (hit on CS+).", 0)
    speed: int = _d("Speed in inches/hexes.", 0)
    heat_limit: int = _d("Heat limit.", 0)
    platforms: int = _d("Platform slots.", 0)
    cost: int = _d("Total price: mech + weapons + ammo + upgrades ($).", 0)
    n_ranged: int = _d("Count of ranged weapons.", 0)
    n_melee: int = _d("Count of melee weapons.", 0)
    upgrades: str = _d("JSON list of upgrade ids.", "[]")
    damage_weapon: int = _d("Enemy damage dealt by weapons (hull points through armor).", 0)
    damage_explosion: int = _d("Enemy damage from this mech's death explosion.", 0)
    damage_self_destruct: int = _d("Enemy damage from this mech's Self Destruct.", 0)
    damage_other: int = _d("Enemy damage from ram and terrain collapse.", 0)
    friendly_damage: int = _d("Damage dealt to own side (incl. self). EXCLUDED from "
                              "damage_* metrics; includes Rail Weapon friendly fire.", 0)
    damage_taken: int = _d("Hull damage this mech took, from any source.", 0)
    kills: int = _d("Enemy mechs whose last damage came from this mech.", 0)
    attacks: int = _d("Attack rolls made (all weapons, incl. free attacks).", 0)
    hits: int = _d("Attacks that hit (incl. crits).", 0)
    crits: int = _d("Attacks that crit.", 0)
    heat_gained: int = _d("Total heat gained over the game.", 0)
    survived: int = _d("1 if still in action at game end.", 0)
    out_round: int = _d("Round it went out of action, 0 if it survived.", 0)
    out_cause: str = _d("damage | overheat | catastrophic | self_destruct | '' .", "")
    hp_final: int = _d("Hull points at game end.", 0)
    heat_final: int = _d("Heat at game end.", 0)


@dataclass
class WeaponRow:
    seed: int = _d("Game seed.", 0)
    unit_id: str = _d("Owning unit id.", "")
    slot: int = _d("Weapon index on the mech; -1 for synthetic weapons.", 0)
    weapon_id: str = _d("Weapon id, or explosion | self_destruct | ram | terrain_collapse.", "")
    kind: str = _d("ranged | melee | synthetic.", "")
    ammo_id: str = _d("Specialty ammo loaded, '' if none.", "")
    attacks: int = _d("Attack rolls with this weapon.", 0)
    hits: int = _d("Hits (incl. crits).", 0)
    crits: int = _d("Crits.", 0)
    damage: int = _d("Enemy damage dealt (friendly damage excluded).", 0)
    friendly_damage: int = _d("Damage to own side from this weapon (excluded elsewhere).", 0)


def unit_cost(rules: Ruleset, u: Unit) -> int:
    """Mech price plus every weapon, its ammo and every upgrade (modded frames are free)."""
    total = int(rules.raw["game"]["mech_cost"])
    for w in u.weapons:
        total += int(rules.weapon(w.weapon_id).get("cost", 0))
        if w.ammo_id:
            total += int(rules.ammo_spec(w.ammo_id).get("cost", 0))
    return total + sum(int(rules.upgrade(x).get("cost", 0)) for x in u.upgrades)


def extract(
    initial: GameState, final: GameState, events, rules: Ruleset, seed: int
) -> tuple[list[UnitRow], list[WeaponRow]]:
    units: dict[str, UnitRow] = {}
    weapons: dict[tuple[str, int], WeaponRow] = {}
    for u in initial.units.values():
        units[u.id] = UnitRow(
            seed=seed, unit_id=u.id, side=u.side, name=u.name,
            frame=u.profile.split(".")[-1], leader=int(bool(u.perk)), perk=u.perk,
            hp_max=u.hp_max, ar=u.ar, cs=u.cs, speed=u.speed, heat_limit=u.heat_limit,
            platforms=u.platforms, cost=unit_cost(rules, u),
            n_ranged=sum(1 for w in u.weapons if w.kind == "ranged"),
            n_melee=sum(1 for w in u.weapons if w.kind == "melee"),
            upgrades=json.dumps(list(u.upgrades)),
        )
        for i, w in enumerate(u.weapons):
            weapons[(u.id, i)] = WeaponRow(
                seed=seed, unit_id=u.id, slot=i, weapon_id=w.weapon_id, kind=w.kind,
                ammo_id=w.ammo_id or "",
            )

    def synthetic(uid: str, name: str) -> WeaponRow:
        key = (uid, -1 - SYNTHETIC_WEAPONS.index(name))
        if key not in weapons:
            weapons[key] = WeaponRow(seed=seed, unit_id=uid, slot=-1, weapon_id=name,
                                     kind="synthetic")
        return weapons[key]

    rnd = 1
    last_source: dict[str, str] = {}
    last_slot: dict[str, int] = {}  # attacker -> slot of its most recent attack
    for e in events:
        k, d = e.kind, e.data
        if k == "phase_start":
            rnd = d.get("round", rnd)
        elif k == "attack":
            a = units.get(d["attacker"])
            if a is None:
                continue
            slot = d.get("weapon_index", -1)
            last_slot[a.unit_id] = slot
            hit = d["outcome"] in ("hit", "crit")
            crit = d["outcome"] == "crit"
            a.attacks += 1
            a.hits += hit
            a.crits += crit
            w = weapons.get((a.unit_id, slot))
            if w is not None:
                w.attacks += 1
                w.hits += hit
                w.crits += crit
        elif k == "heat_gain":
            if d["unit"] in units and d["amount"] > 0:
                units[d["unit"]].heat_gained += d["amount"]
        elif k == "damage":
            amt = int(d["amount"])
            if d["target"] in units:
                units[d["target"]].damage_taken += amt
            last_source[d["target"]] = d.get("source")
            dealer = d.get("dealer")
            if dealer not in units:
                continue  # unattributed (e.g. catastrophic ricochet)
            du, weapon, cause = units[dealer], d.get("weapon"), d.get("cause")
            if d.get("friendly"):
                # Friendly fire (Rail Weapon lane hits, blasts catching a friend, ram
                # self-damage) is deliberately NOT counted as damage dealt.
                du.friendly_damage += amt
                if cause == "weapon":
                    w = weapons.get((dealer, last_slot.get(dealer, -1)))
                    if w is not None:
                        w.friendly_damage += amt
                elif weapon in SYNTHETIC_WEAPONS:
                    synthetic(dealer, weapon).friendly_damage += amt
            elif weapon == "explosion":
                du.damage_explosion += amt
                synthetic(dealer, "explosion").damage += amt
            elif weapon == "self_destruct":
                du.damage_self_destruct += amt
                synthetic(dealer, "self_destruct").damage += amt
            elif cause == "weapon":
                du.damage_weapon += amt
                w = weapons.get((dealer, last_slot.get(dealer, -1)))
                if w is not None:
                    w.damage += amt
            else:
                du.damage_other += amt
                if weapon in SYNTHETIC_WEAPONS:
                    synthetic(dealer, weapon).damage += amt
        elif k == "out_of_action":
            v = units.get(d["unit"])
            if v is None:
                continue
            v.out_round, v.out_cause = rnd, d.get("cause", "")
            killer = units.get(last_source.get(v.unit_id) or "")
            if v.out_cause in ("damage", "catastrophic") and killer and killer.side != v.side:
                killer.kills += 1

    for uid, row in units.items():
        fu = final.units[uid]
        row.survived = int(not fu.out_of_action)
        row.hp_final, row.heat_final = fu.hp, fu.heat
        if row.survived:
            row.out_round, row.out_cause = 0, ""
    return list(units.values()), list(weapons.values())
