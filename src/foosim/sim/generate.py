"""Random Mech / Combat Unit generation, seeded off the Black Market tables.

  foosim-gen-unit --seed 3 --count 4

``generate_squad`` builds a quick-play squad (Heavy leader with one perk, 2 Medium,
1 Light) - the same logic behind the printable ``foosim-sheet``. ``generate_mech``
fills a frame's Platform slots by rolling weapons (d8) and
upgrades (d20); Heavy Weapon eats 2 slots, Extra Platforms grants one. Call signs
come from the two d66 tables. ``random_setup`` drops two generated units on the
skirmish map for varied auto-battles.
"""

from __future__ import annotations

import argparse

from foosim.engine.effects import (
    ammo_supported,
    perk_supported,
    upgrade_supported,
    weapon_supported,
)
from foosim.engine.hexgrid import Hex, from_offset_oddr
from foosim.engine.rng import Rng
from foosim.engine.rules import Ruleset
from foosim.engine.rules import load as load_rules
from foosim.engine.state import GameState, MapSpec, Unit, WeaponInstance
from foosim.sim.build import apply_upgrades
from foosim.sim.setups import _zone_rows, city_terrain, scatter_terrain

__all__ = [
    "SQUAD_FRAMES",
    "call_sign",
    "generate_combat_unit",
    "generate_mech",
    "generate_squad",
    "pick_perk",
    "random_setup",
]

# Quick-play squad makeup: a Heavy squad leader, two Mediums and a Light.
SQUAD_FRAMES = ("heavy", "medium", "medium", "light")

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
    supported_only: bool = True,
    frame: str | None = None,
) -> Unit:
    """Roll a mech from the Black Market tables. With ``supported_only`` (default)
    a rolled weapon/upgrade/ammo whose ``special`` behaviour is not implemented
    yet (see ``engine.effects``) is skipped and re-rolled, so random mechs never
    carry inert gear. ``frame`` forces light/medium/heavy instead of rolling one."""
    _index(rules)
    frame = frame or rules.frame_for_roll(rng.d6())
    f = rules.frame(frame)
    slots = int(f["platform_slots"])

    weapons: list[WeaponInstance] = []
    upgrades: list[str] = []
    guard = 0
    while slots > 0 and guard < 80:
        guard += 1
        if rng.d6() <= 4:  # weapon
            kind = "ranged" if rng.d6() <= 3 else "melee"
            wid = (_RANGED_BY_ROLL if kind == "ranged" else _MELEE_BY_ROLL)[rng.die(8)]
            wspec = rules.weapon(wid)
            if supported_only and not weapon_supported(wspec):
                continue
            cost = int(wspec.get("platform_slots", 1))
            if cost > slots:
                continue
            slots -= cost
            weapons.append(WeaponInstance(weapon_id=wid, kind=kind))
        else:  # upgrade
            up = rules.raw["upgrades"][rng.randint(0, len(rules.raw["upgrades"]) - 1)]
            if not up.get("stackable") and up["id"] in upgrades:
                continue
            if supported_only and not upgrade_supported(up):
                continue
            upgrades.append(up["id"])
            slots -= 1
            if up.get("effect", {}).get("free_slot"):
                slots += 1  # Extra Platforms does not consume a slot

    # ammo on some ranged weapons (Flame Thrower takes none)
    ammo = [a for a in rules.raw["ammo"] if not supported_only or ammo_supported(a)]
    for w in weapons:
        if w.kind != "ranged" or not ammo:
            continue
        if "no_specialty_ammo" in set(rules.weapon(w.weapon_id).get("special", [])):
            continue
        if rng.random() < ammo_chance:
            w.ammo_id = ammo[rng.randint(0, len(ammo) - 1)]["id"]

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


def pick_perk(rules: Ruleset, rng: Rng, u: Unit, *, supported_only: bool = True) -> dict:
    """Give ``u`` one random Experience perk (optional rules, p.21) and bake its stat
    delta in. Never a melee bonus on a mech with no melee weapon or a ranged bonus on
    one with no ranged weapon; with ``supported_only`` only perks the sim can honour."""
    kinds = {w.kind for w in u.weapons} | {"any"}
    ok = [
        p for p in rules.raw["perks"]
        if p.get("requires", "any") in kinds and (not supported_only or perk_supported(p))
    ]
    perk = ok[rng.randint(0, len(ok) - 1)]
    eff = perk.get("effect", {})
    u.speed += int(eff.get("speed_delta", 0))
    u.heat_limit += int(eff.get("heat_limit_delta", 0))
    return perk


def generate_squad(
    rules: Ruleset, rng: Rng, side: int, *, n: int = 4, id_prefix: str = "U",
    supported_only: bool = True,
) -> tuple[list[Unit], dict]:
    """A quick-play squad: Heavy leader (first unit, one perk), two Mediums, a Light;
    extra units beyond four are Mediums. Returns the units and the leader's perk."""
    units: list[Unit] = []
    perk: dict = {}
    for i in range(n):
        frame = SQUAD_FRAMES[i] if i < len(SQUAD_FRAMES) else "medium"
        u = generate_mech(rules, rng, id=f"{id_prefix}{i + 1}", side=side, frame=frame,
                          supported_only=supported_only)
        if i == 0:
            perk = pick_perk(rules, rng, u, supported_only=supported_only)
        units.append(u)
    return units, perk


def generate_combat_unit(
    rules: Ruleset, rng: Rng, side: int, *, n: int = 4, id_prefix: str = "U",
    supported_only: bool = True,
) -> list[Unit]:
    return generate_squad(rules, rng, side, n=n, id_prefix=id_prefix,
                          supported_only=supported_only)[0]


def random_setup(
    rules: Ruleset,
    *,
    seed: int,
    n: int = 4,
    cols: int = 30,
    rows: int = 30,
    terrain: str = "city",
    supported_only: bool = True,
    squad_seed_0: int | None = None,
    squad_seed_1: int | None = None,
    terrain_seed: int | None = None,
) -> GameState:
    """Two randomly generated ``n``-mech combat units on a square board. Default
    is a 4v4 on a 30x30 urban map (matching how the game is usually played);
    ``terrain`` is ``"city"`` (dense blocking + cover), ``"scatter"``, or ``"none"``.

    Isolating variables: ``seed`` drives everything by default (squads, terrain, game
    dice). ``squad_seed_0`` / ``squad_seed_1`` pin that side's squad (frames, gear, call
    signs, perk) to its own seed, so it is the same in every game while the other side,
    the map and the dice still vary with ``seed``; the same value on both sides gives a
    mirror match. ``terrain_seed`` likewise pins the map."""
    rng = Rng.from_seed(seed ^ 0x6E_4E_5A)
    pinned = {0: squad_seed_0, 1: squad_seed_1}
    mapspec = MapSpec(
        cols=cols, rows=rows, name=f"random_{terrain}",
        deploy_zones={
            0: _zone_rows(cols, range(0, 3)),
            1: _zone_rows(cols, range(rows - 3, rows)),
        },
    )
    units: dict[str, Unit] = {}
    span = cols // (n + 1)
    for side in (0, 1):
        row = 1 if side == 0 else rows - 2
        side_rng = rng if pinned[side] is None else Rng.from_seed(pinned[side] ^ 0x51_AD_0E)
        squad = generate_combat_unit(rules, side_rng, side, n=n, id_prefix="AB"[side],
                                     supported_only=supported_only)
        for k, u in enumerate(squad):
            u.pos = from_offset_oddr(span * (k + 1), row)
            units[u.id] = u
    avoid = (
        set(mapspec.deploy_zones[0]) | set(mapspec.deploy_zones[1])
        | {u.pos for u in units.values()}
    )
    terr_rng = Rng.from_seed((seed if terrain_seed is None else terrain_seed) ^ 0x5CA_77E4)
    if terrain == "city":
        terr = city_terrain(mapspec, terr_rng, avoid=avoid)
    elif terrain == "scatter":
        terr = scatter_terrain(mapspec, terr_rng, avoid=avoid, n_blockers=8, n_cover=12)
    else:
        terr = {}
    return GameState(
        mapspec=mapspec, mission="warzone", rng_state=Rng.from_seed(seed).state,
        units=units, terrain=terr, pass_tokens={0: 0, 1: 0}, initiative=(0, 1),
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
    ap.add_argument("--full", action="store_true",
                    help="use the whole Black Market table, incl. not-yet-implemented gear")
    args = ap.parse_args(argv)
    rules = load_rules()
    rng = Rng.from_seed(args.seed)
    for i in range(args.count):
        u = generate_mech(rules, rng, id=f"M{i + 1}", side=0, supported_only=not args.full)
        print(_stat_block(u))
        print()


if __name__ == "__main__":  # pragma: no cover
    main()
