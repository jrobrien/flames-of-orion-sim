"""Canned battle setups for tests, demos, and the analysis harness.

Unit construction here is deliberately minimal (enough for M3); the full random
generator lands in ``sim/generate.py`` at M7. ``mech()`` pulls base stats from a
Ruleset frame and carries a weapon list; static upgrade stat-baking is TODO.
"""

from __future__ import annotations

from collections.abc import Iterable

from foosim.engine import hexgrid
from foosim.engine.hexgrid import Hex, from_offset_oddr
from foosim.engine.rng import Rng
from foosim.engine.rules import Ruleset
from foosim.engine.state import GameState, MapSpec, TerrainHex, Unit, WeaponInstance
from foosim.sim.build import apply_upgrades

__all__ = ["city_terrain", "mech", "scatter_terrain", "skirmish_2v2"]

_TERRAIN_SALT = 0x5CA_77E4  # keeps the terrain RNG stream clear of the policy seeds


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
    unit = Unit(
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
    apply_upgrades(unit, rules)
    return unit


def _zone_rows(cols: int, rows: range) -> tuple[Hex, ...]:
    return tuple(from_offset_oddr(c, r) for r in rows for c in range(cols))


def scatter_terrain(
    mapspec: MapSpec,
    rng: Rng,
    *,
    avoid: set[Hex],
    n_blockers: int = 4,
    n_cover: int = 5,
) -> dict[Hex, TerrainHex]:
    """Seeded procedural obstructions: a few LOS-blocking buildings (1-3 hex
    clumps, mostly destructible) plus scattered low cover, none overlapping
    ``avoid`` (deploy zones + unit hexes)."""
    cells = mapspec.cells()
    candidates = [h for h in sorted(cells) if h not in avoid]
    rng.shuffle(candidates)
    out: dict[Hex, TerrainHex] = {}

    def free(h: Hex) -> bool:
        return h in cells and h not in avoid and h not in out

    i = 0
    for _ in range(n_blockers):
        while i < len(candidates) and not free(candidates[i]):
            i += 1
        if i >= len(candidates):
            break
        seed_h = candidates[i]
        i += 1
        clump = [seed_h]
        target = 1 + rng.randint(0, 2)
        for nb in hexgrid.neighbors(seed_h):
            if len(clump) >= target:
                break
            if free(nb):
                clump.append(nb)
        tags = {"blocking", "indestructible"} if rng.d6() <= 2 else {"blocking", "destructible"}
        height = float(rng.randint(1, 3))
        for h in clump:
            out[h] = TerrainHex(pos=h, tags=set(tags), height=height)

    for _ in range(n_cover):
        while i < len(candidates) and not free(candidates[i]):
            i += 1
        if i >= len(candidates):
            break
        h = candidates[i]
        i += 1
        out[h] = TerrainHex(pos=h, tags={"cover"}, height=0.5)

    return out


def _grow(seed: Hex, size: int, ok, rng: Rng) -> list[Hex]:
    clump = [seed]
    frontier = [seed]
    while len(clump) < size and frontier:
        h = frontier[rng.randint(0, len(frontier) - 1)]
        nbrs = [n for n in hexgrid.neighbors(h) if n not in clump and ok(n)]
        if not nbrs:
            frontier.remove(h)
            continue
        pick = nbrs[rng.randint(0, len(nbrs) - 1)]
        clump.append(pick)
        frontier.append(pick)
    return clump


def city_terrain(
    mapspec: MapSpec,
    rng: Rng,
    *,
    avoid: set[Hex],
    building_frac: float = 0.09,
    cover_frac: float = 0.05,
) -> dict[Hex, TerrainHex]:
    """A dense urban board. Terrain kinds:

    * **buildings** - 2-hex footprints, height 1", ``blocking`` + ``cover`` +
      ``indestructible``; mechs traverse *over* them (climb cost 1").
    * **low cover** - 1 hex, height 0.5", ``cover`` + ``destructible`` (only
      explosions raze it); does not block LOS.
    * a stepped central **hill** via ``mapspec.elevation`` (0.5" outer, 1"
      inner, 1.5" peak) - indestructible ground you stand on and see over.
    """
    cells = mapspec.cells()
    cx, cy = mapspec.cols // 2, mapspec.rows // 2
    margin = 3  # keep terrain off the deploy rows
    interior = [
        h for h in sorted(cells)
        if h not in avoid and margin <= hexgrid.to_offset_oddr(h)[1] < mapspec.rows - margin
    ]
    out: dict[Hex, TerrainHex] = {}

    # stepped hill in the middle
    for h in interior:
        col, row = hexgrid.to_offset_oddr(h)
        d = max(abs(col - cx), abs(row - cy))
        if d <= 1:
            mapspec.elevation[h] = 1.5
        elif d <= 3:
            mapspec.elevation[h] = 1.0
        elif d <= 5:
            mapspec.elevation[h] = 0.5

    rng.shuffle(interior)
    i = 0

    def free(h: Hex) -> bool:
        return h in cells and h not in avoid and h not in out

    n_buildings = int(len(interior) * building_frac / 2)  # 2 hexes each
    for _ in range(n_buildings):
        while i < len(interior) and not free(interior[i]):
            i += 1
        if i >= len(interior):
            break
        clump = _grow(interior[i], 2, free, rng)
        i += 1
        for h in clump:
            out[h] = TerrainHex(pos=h, tags={"blocking", "cover", "indestructible"}, height=1.0)

    for _ in range(int(len(interior) * cover_frac)):
        while i < len(interior) and not free(interior[i]):
            i += 1
        if i >= len(interior):
            break
        out[interior[i]] = TerrainHex(pos=interior[i], tags={"cover", "destructible"}, height=0.5)
        i += 1

    return out


def _fixed_terrain() -> dict[Hex, TerrainHex]:
    building = [from_offset_oddr(7, 6), from_offset_oddr(8, 6), from_offset_oddr(7, 7)]
    terr: dict[Hex, TerrainHex] = {
        h: TerrainHex(pos=h, tags={"blocking", "destructible"}, height=1.0) for h in building
    }
    pillar = from_offset_oddr(3, 5)
    terr[pillar] = TerrainHex(pos=pillar, tags={"blocking", "indestructible"}, height=2.0)
    return terr


def skirmish_2v2(rules: Ruleset, *, seed: int = 1, terrain: str = "scatter") -> GameState:
    """A 16x12 board, two medium mechs a side on opposite edges.

    ``terrain``: ``"scatter"`` (seeded procedural, default), ``"fixed"`` (a
    hand-placed building + pillar), or ``"none"`` (open field)."""
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

    if terrain == "fixed":
        terr = _fixed_terrain()
    elif terrain == "none":
        terr = {}
    elif terrain == "scatter":
        avoid = (
            set(mapspec.deploy_zones[0])
            | set(mapspec.deploy_zones[1])
            | {u.pos for u in units.values()}
        )
        terr = scatter_terrain(mapspec, Rng.from_seed(seed ^ _TERRAIN_SALT), avoid=avoid)
    else:
        raise ValueError(f"unknown terrain mode: {terrain!r}")

    return GameState(
        mapspec=mapspec,
        mission="warzone",
        rng_state=Rng.from_seed(seed).state,
        units=units,
        terrain=terr,
        pass_tokens={0: 0, 1: 0},
        initiative=(0, 1),
    )
