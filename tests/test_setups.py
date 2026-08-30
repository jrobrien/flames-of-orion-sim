import json

from foosim.engine.rules import load
from foosim.engine.state import GameState
from foosim.sim.setups import skirmish_2v2


def test_skirmish_2v2_shape():
    gs = skirmish_2v2(load(), seed=1)
    assert len(gs.units) == 4
    assert sorted(u.side for u in gs.units.values()) == [0, 0, 1, 1]
    assert gs.mission == "warzone"
    assert gs.rng_state != 0


def test_all_units_in_bounds_and_not_stacked():
    gs = skirmish_2v2(load())
    positions = [u.pos for u in gs.units.values()]
    assert len(set(positions)) == len(positions)
    assert all(gs.mapspec.in_bounds(p) for p in positions)


def test_units_deploy_in_their_zones():
    gs = skirmish_2v2(load())
    for u in gs.units.values():
        assert u.pos in gs.mapspec.deploy_zones[u.side]


def test_terrain_present_and_typed():
    gs = skirmish_2v2(load())
    assert any("destructible" in t.tags for t in gs.terrain.values())
    assert any("indestructible" in t.tags for t in gs.terrain.values())
    assert all(gs.mapspec.in_bounds(h) for h in gs.terrain)


def test_setup_roundtrips():
    gs = skirmish_2v2(load(), seed=7)
    assert GameState.from_dict(json.loads(json.dumps(gs.to_dict()))) == gs


def test_mech_stats_come_from_frame():
    r = load()
    gs = skirmish_2v2(r)
    u = gs.units["A1"]
    f = r.frame("medium")
    assert (u.cs, u.ar, u.speed, u.hp_max, u.heat_limit) == (
        f["combat_skill"],
        f["armor"],
        f["speed"],
        f["hull_points"],
        f["heat_limit"],
    )
    assert u.hp == u.hp_max
    assert {w.kind for w in u.weapons} == {"ranged", "melee"}
