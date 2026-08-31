"""Random Mech / Combat Unit generation, seeded off the Black Market tables.

  foosim-gen-unit --seed 3 --count 4

``generate_mech`` fills a frame's Platform slots by rolling weapons (d8) and
upgrades (d20); Heavy Weapon eats 2 slots, Extra Platforms grants one. Call signs
come from the two d66 tables. ``random_setup`` drops two generated units on the
skirmish map for varied auto-battles.
"""

from __future__ import annotations

import argparse

from foosim.engine.hexgrid import Hex, from_offset_oddr
from foosim.engine.rng import Rng
from foosim.engine.rules import Ruleset
from foosim.engine.rules import load as load_rules
from foosim.engine.state import GameState, MapSpec, Unit, WeaponInstance
from foosim.sim.build import apply_upgrades
from foosim.sim.setups import _zone_rows, scatter_terrain

__all__ = ["call_sign", "generate_combat_unit", "generate_mech", "random_setup"]

_RANGED_BY_ROLL: dict[int, str] = {}
_MELEE_BY_ROLL: dict[int, str] = {}


def _index(rules: Ruleset) -> None:
    if not _RANGED_BY_ROLL:
        _RANGED_BY_ROLL.update({w["roll"]: w["id"] for w in rules.raw["ranged_weapons"]})
        _MELEE_BY_ROLL.update({w["roll"]: w["id"] for w in rules.raw["melee_weapons"]})


def call_sign(rules: Ruleset, rng: Rng) -> str:
    cs = rules.raw["call_sign"]
    a = cs["table_a"][rng.randint(0, 5)][rng.randint(0, 5)]
    b = cs["table_b"][rng.randint(0, 5)][rng.randint(0, 5)]
    return f"{a} {b}"


def generate_mech(
    rules: Ruleset,
    rng: Rng,
    *,
    id: str,
    side: int,
    pos: Hex | None = None,
    ammo_chance: float = 0.4,
) -> Unit:
    _index(rules)
    frame = rules.frame_for_roll(rng.d6())
    f = rules.frame(frame)
    slots = int(f["platform_slots"])

    weapons: list[WeaponInstance] = []
    upgrades: list[str] = []
    guard = 0
    while slots > 0 and guard < 40:
        guard += 1
        if rng.d6() <= 4:  # weapon
            if rng.d6() <= 3:
                wid = _RANGED_BY_ROLL[rng.die(8)]
                kind = "ranged"
            else:
                wid = _MELEE_BY_ROLL[rng.die(8)]
                kind = "melee"
            cost = int(rules.weapon(wid).get("platform_slots", 1))
            if cost > slots:
                continue
            slots -= cost
            weapons.append(WeaponInstance(weapon_id=wid, kind=kind))
        else:  # upgrade
            up = rules.raw["upgrades"][rng.randint(0, len(rules.raw["upgrades"]) - 1)]
            if not up.get("stackable") and up["id"] in upgrades:
                continue
            upgrades.append(up["id"])
            slots -= 1
            if up.get("effect", {}).get("free_slot"):
                slots += 1  # Extra Platforms does not consume a slot

    # ammo on some ranged weapons (Flame Thrower takes none)
    ammo_ids = [a["id"] for a in rules.raw["ammo"]]
    for w in weapons:
        if w.kind != "ranged":
            continue
        if "no_specialty_ammo" in set(rules.weapon(w.weapon_id).get("special", [])):
            continue
        if rng.random() < ammo_chance:
            w.ammo_id = ammo_ids[rng.randint(0, len(ammo_ids) - 1)]

    unit = Unit(
        id=id,
        side=side,
        name=call_sign(rules, rng),
        profile=f"mech.{frame}",
        hp_max=int(f["hull_points"]),
        ar=int(f["armor"]),
        cs=int(f["combat_skill"]),
        speed=int(f["speed"]),
        heat_limit=int(f["heat_limit"]),
        platforms=int(f["platform_slots"]),
        pos=pos or Hex(0, 0),
        weapons=weapons,
        upgrades=upgrades,
    )
    apply_upgrades(unit, rules)
    return unit


def generate_combat_unit(
    rules: Ruleset, rng: Rng, side: int, *, n: int = 4, id_prefix: str = "U"
) -> list[Unit]:
    return [generate_mech(rules, rng, id=f"{id_prefix}{i + 1}", side=side) for i in range(n)]


def random_setup(rules: Ruleset, *, seed: int, n: int = 2) -> GameState:
    rng = Rng.from_seed(seed ^ 0x6E_4E_5A)
    cols, rows = 16, 12
    mapspec = MapSpec(
        cols=cols, rows=rows, name="random_skirmish",
        deploy_zones={
            0: _zone_rows(cols, range(0, 2)),
            1: _zone_rows(cols, range(rows - 2, rows)),
        },
    )
    units: dict[str, Unit] = {}
    for side in (0, 1):
        row = 1 if side == 0 else rows - 2
        squad = generate_combat_unit(rules, rng, side, n=n, id_prefix="AB"[side])
        cols_used = list(range(2, 2 + 3 * n, 3))
        for u, col in zip(squad, cols_used, strict=True):
            u.pos = from_offset_oddr(col, row)
            units[u.id] = u
    avoid = (
        set(mapspec.deploy_zones[0]) | set(mapspec.deploy_zones[1])
        | {u.pos for u in units.values()}
    )
    terrain = scatter_terrain(mapspec, Rng.from_seed(seed ^ 0x5CA_77E4), avoid=avoid)
    return GameState(
        mapspec=mapspec, mission="warzone", rng_state=Rng.from_seed(seed).state,
        units=units, terrain=terrain, pass_tokens={0: 0, 1: 0}, initiative=(0, 1),
    )


def _stat_block(u: Unit) -> str:
    lines = [
        f"{u.id}  \"{u.name}\"  [{u.profile}]",
        f"  S{u.speed} CS{u.cs}+ AR{u.ar}+ HP{u.hp_max} HL{u.heat_limit} PF{u.platforms}",
    ]
    for w in u.weapons:
        ammo = f" + {w.ammo_id}" if w.ammo_id else ""
        lines.append(f"  [{w.kind[0].upper()}] {w.weapon_id}{ammo}")
    if u.upgrades:
        lines.append("  upgrades: " + ", ".join(u.upgrades))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Generate random Flames of Orion mechs")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--count", type=int, default=4)
    args = ap.parse_args(argv)
    rules = load_rules()
    rng = Rng.from_seed(args.seed)
    for i in range(args.count):
        print(_stat_block(generate_mech(rules, rng, id=f"M{i + 1}", side=0)))
        print()


if __name__ == "__main__":  # pragma: no cover
    main()
