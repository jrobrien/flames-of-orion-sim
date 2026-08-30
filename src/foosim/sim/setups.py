"""Canned battle setups for tests, demos, and the analysis harness.

Unit construction here is deliberately minimal (enough for M3); the full random
generator lands in ``sim/generate.py`` at M7. ``mech()`` pulls base stats from a
Ruleset frame and carries a weapon list; static upgrade stat-baking is TODO.
"""

from __future__ import annotations

from collections.abc import Iterable

from foosim.engine.hexgrid import Hex, from_offset_oddr
from foosim.engine.rng import Rng
from foosim.engine.rules import Ruleset
from foosim.engine.state import GameState, MapSpec, TerrainHex, Unit, WeaponInstance

__all__ = ["mech", "skirmish_2v2"]


def mech(
    rules: Ruleset,
    *,
    id: str,
    side: int,
    name: str,
    pos: Hex,
    frame: str = "medium",
    ranged: Iterable[str] = (),
    melee: Iterable[str] = (),
    upgrades: Iterable[str] = (),
) -> Unit:
    f = rules.frame(frame)
    weapons = [WeaponInstance(weapon_id=w, kind="ranged") for w in ranged]
    weapons += [WeaponInstance(weapon_id=w, kind="melee") for w in melee]
    return Unit(
        id=id,
        side=side,
        name=name,
        profile=f"mech.{frame}",
        hp_max=int(f["hull_points"]),
        ar=int(f["armor"]),
        cs=int(f["combat_skill"]),
        speed=int(f["speed"]),
        heat_limit=int(f["heat_limit"]),
        platforms=int(f["platform_slots"]),
        pos=pos,
        weapons=weapons,
        upgrades=list(upgrades),
    )


def _zone_rows(cols: int, rows: range) -> tuple[Hex, ...]:
    return tuple(from_offset_oddr(c, r) for r in rows for c in range(cols))


def skirmish_2v2(rules: Ruleset, *, seed: int = 1) -> GameState:
    """A 16x12 board, one destructible building + one hard blocker mid-field,
    two medium mechs a side on opposite edges."""
    cols, rows = 16, 12
    mapspec = MapSpec(
        cols=cols,
        rows=rows,
        name="skirmish_2v2",
        deploy_zones={
            0: _zone_rows(cols, range(0, 2)),
            1: _zone_rows(cols, range(rows - 2, rows)),
        },
    )

    building = [from_offset_oddr(7, 6), from_offset_oddr(8, 6), from_offset_oddr(7, 7)]
    terrain: dict[Hex, TerrainHex] = {
        h: TerrainHex(pos=h, tags={"blocking", "destructible"}, height=1.0)
        for h in building
    }
    pillar = from_offset_oddr(3, 5)
    terrain[pillar] = TerrainHex(pos=pillar, tags={"blocking", "indestructible"}, height=2.0)

    loadout = {"ranged": ("medium_weapon",), "melee": ("close_combat_weapon",)}
    units = {
        u.id: u
        for u in (
            mech(rules, id="A1", side=0, name="Iron Talon", pos=from_offset_oddr(5, 1),
                 ranged=loadout["ranged"], melee=loadout["melee"]),
            mech(rules, id="A2", side=0, name="Dark Sentinel", pos=from_offset_oddr(10, 1),
                 ranged=loadout["ranged"], melee=loadout["melee"]),
            mech(rules, id="B1", side=1, name="Void Reaver", pos=from_offset_oddr(5, 10),
                 ranged=loadout["ranged"], melee=loadout["melee"]),
            mech(rules, id="B2", side=1, name="Grim Wyvern", pos=from_offset_oddr(10, 10),
                 ranged=loadout["ranged"], melee=loadout["melee"]),
        )
    }

    return GameState(
        mapspec=mapspec,
        mission="warzone",
        rng_state=Rng.from_seed(seed).state,
        units=units,
        terrain=terrain,
        pass_tokens={0: 0, 1: 0},
        initiative=(0, 1),
    )
