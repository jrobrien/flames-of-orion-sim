"""Traversable terrain: climb cost, steep-step limit, elevation LOS, explosions."""

import pytest

from _helpers import duel, rng_state_for_rolls
from foosim.engine import legal, resolve
from foosim.engine.actions import IllegalAction, MoveAction
from foosim.engine.hexgrid import Hex
from foosim.engine.rng import Rng
from foosim.engine.rules import load
from foosim.engine.state import GameState, MapSpec, TerrainHex
from foosim.engine.visibility import line_of_sight
from foosim.sim.setups import city_terrain, mech

RULES = load()


def _state(terrain=None, elevation=None):
    u = mech(RULES, id="U", side=0, name="U", pos=Hex(0, 0))
    gs = GameState(mapspec=MapSpec(14, 14), units={"U": u}, pass_tokens={0: 0, 1: 0})
    for h, t in (terrain or {}).items():
        gs.terrain[h] = t
    for h, v in (elevation or {}).items():
        gs.mapspec.elevation[h] = v
    return gs, u


# -- movement --------------------------------------------------------------


def test_terrain_is_traversable_with_climb_cost():
    b = {Hex(0, 1): TerrainHex(Hex(0, 1), {"blocking", "indestructible"}, 1.0)}
    gs, u = _state(terrain=b)
    paths = legal.move_paths(gs, u, budget=u.stat("speed"))
    assert Hex(0, 1) in paths  # can climb onto the roof
    assert Hex(0, 2) in paths  # and continue past it
    # onto the 1" roof: step cost 1 + 1 climb = 2, then 1 per flat step
    _, ev = resolve.apply(gs, MoveAction("U", [Hex(0, 0), Hex(0, 1), Hex(0, 2)]), RULES)
    mv = next(e for e in ev if e.kind == "move")
    assert mv.data["cost"] == pytest.approx(3.0)  # 2 up + 1 down (descent free -> just +1)


def test_step_cost_helper():
    assert legal.step_cost(0.0, 1.0) == 2.0   # climb 1"
    assert legal.step_cost(1.5, 0.0) == 1.0   # descent is free
    assert legal.step_cost(0.5, 0.5) == 1.0


def test_too_steep_a_step_is_illegal():
    gs, u = _state(elevation={Hex(0, 1): 3.0})  # a 3" cliff, > 2" limit
    with pytest.raises(IllegalAction):
        resolve.apply(gs, MoveAction("U", [Hex(0, 0), Hex(0, 1)]), RULES)
    assert Hex(0, 1) not in legal.move_paths(gs, u, budget=u.stat("speed"))


def test_vtol_ignores_terrain_and_height():
    gs, u = _state(terrain={Hex(0, 1): TerrainHex(Hex(0, 1), {"blocking"}, 1.0)},
                   elevation={Hex(0, 2): 5.0})
    u.ignores_terrain_on_move = True
    paths = legal.move_paths(gs, u, budget=u.stat("speed"))
    assert Hex(0, 2) in paths  # flies over the 5" pillar
    _, ev = resolve.apply(gs, MoveAction("U", [Hex(0, 0), Hex(0, 1), Hex(0, 2)]), RULES)
    assert next(e for e in ev if e.kind == "move").data["cost"] == 2.0  # flat, 1 per step


# -- elevation LOS (multiray, the default mode) -------------------------


def test_elevated_observer_sees_over_a_wall_that_blocks_the_ground():
    wall = {Hex(0, 3): TerrainHex(Hex(0, 3), {"blocking"}, 1.0)}
    gs, _ = _state(terrain=wall)
    assert not line_of_sight(gs, Hex(0, 0), Hex(0, 6)).los  # both on the ground
    gs.mapspec.elevation[Hex(0, 0)] = 3.0                    # sniper on a tower
    assert line_of_sight(gs, Hex(0, 0), Hex(0, 6)).los


def test_low_cover_does_not_block_but_grants_cover():
    c = {Hex(0, 3): TerrainHex(Hex(0, 3), {"cover", "destructible"}, 0.5)}
    gs, _ = _state(terrain=c)
    los = line_of_sight(gs, Hex(0, 0), Hex(0, 6))
    assert los.los and los.cover


# -- explosions raze low cover -----------------------------------------


def test_explosion_razes_destructible_cover_not_buildings():
    gs = duel(RULES, a_pos=Hex(0, 0), b_pos=Hex(3, 3),
              rng_state=rng_state_for_rolls([3]))  # explode-check 3 -> boom
    gs.terrain[Hex(0, 1)] = TerrainHex(Hex(0, 1), {"cover", "destructible"}, 0.5)
    gs.terrain[Hex(1, 0)] = TerrainHex(Hex(1, 0), {"blocking", "cover", "indestructible"}, 1.0)
    a = gs.units["A"]
    a.heat = 8  # radius 8
    resolve._explode_check(gs, a, Rng(state=gs.rng_state), RULES, [], cause="t")
    assert gs.terrain[Hex(0, 1)].destroyed          # low cover levelled
    assert not gs.terrain[Hex(1, 0)].destroyed      # building survives


# -- generated city -----------------------------------------------------


def test_city_terrain_kinds():
    m = MapSpec(30, 30, deploy_zones={0: (), 1: ()})
    terr = city_terrain(m, Rng.from_seed(1), avoid=set())
    buildings = [t for t in terr.values() if "blocking" in t.tags]
    covers = [t for t in terr.values() if t.tags == {"cover", "destructible"}]
    assert buildings and covers
    assert all("indestructible" in t.tags and t.height == 1.0 for t in buildings)
    assert all(t.height == 0.5 for t in covers)
    assert set(m.elevation.values()) <= {0.5, 1.0, 1.5}
    # buildings come in 2-hex footprints
    assert len(buildings) % 2 == 0
