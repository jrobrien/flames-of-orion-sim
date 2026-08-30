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


def test_terrain_modes():
    r = load()
    assert skirmish_2v2(r, terrain="none").terrain == {}

    fixed = skirmish_2v2(r, terrain="fixed").terrain
    assert any("destructible" in t.tags for t in fixed.values())
    assert any("indestructible" in t.tags for t in fixed.values())

    gs = skirmish_2v2(r, seed=1)  # default is scatter
    assert gs.terrain
    assert all(gs.mapspec.in_bounds(h) for h in gs.terrain)
    assert any("blocking" in t.tags for t in gs.terrain.values())
    assert any("cover" in t.tags for t in gs.terrain.values())


def test_scatter_is_seeded_reproducible_and_seed_sensitive():
    r = load()
    a = skirmish_2v2(r, seed=5).terrain
    b = skirmish_2v2(r, seed=5).terrain
    c = skirmish_2v2(r, seed=6).terrain
    assert {k: v.to_dict() for k, v in a.items()} == {k: v.to_dict() for k, v in b.items()}
    assert set(a) != set(c)


def test_scatter_never_covers_deploy_zones_or_units():
    r = load()
    for seed in range(20):
        gs = skirmish_2v2(r, seed=seed)
        occupied = {u.pos for u in gs.units.values()}
        zones = set(gs.mapspec.deploy_zones[0]) | set(gs.mapspec.deploy_zones[1])
        assert not (set(gs.terrain) & occupied)
        assert not (set(gs.terrain) & zones)


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
