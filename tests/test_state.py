import json

import pytest

from foosim.engine.hexgrid import Hex
from foosim.engine.state import GameState, MapSpec, TerrainHex, Unit, WeaponInstance
from foosim.engine.visibility import VisibilityConfig, line_of_sight


def _sample_unit() -> Unit:
    return Unit(
        id="A1",
        side=0,
        name="Iron Talon",
        profile="mech.medium",
        hp_max=6,
        ar=6,
        cs=4,
        speed=6,
        heat_limit=10,
        platforms=4,
        pos=Hex(2, -3),
        facing=3,
        weapons=[
            WeaponInstance("medium_weapon", "ranged"),
            WeaponInstance("close_combat_weapon", "melee", ammo_id=None),
        ],
        upgrades=["targeting_system"],
        modifiers={"cs": -1, "speed": 1},
        statuses={"position_compromised": 1},
    )


def test_unit_defaults_hp_to_max():
    u = _sample_unit()
    assert u.hp == 6


def test_unit_stat_applies_modifiers():
    u = _sample_unit()
    assert u.stat("cs") == 3
    assert u.stat("speed") == 7
    assert u.stat("ar") == 6  # no modifier


def test_unit_roundtrip():
    u = _sample_unit()
    assert Unit.from_dict(u.to_dict()) == u


def test_terrain_rejects_unknown_tags():
    with pytest.raises(ValueError):
        TerrainHex.from_dict({"pos": [0, 0], "tags": ["banana"]})


def test_mapspec_offset_bounds_and_cells():
    m = MapSpec(cols=4, rows=3)
    assert len(m.cells()) == 12
    assert all(m.in_bounds(h) for h in m.cells())
    assert not m.in_bounds(Hex(100, 100))


def _sample_state() -> GameState:
    m = MapSpec(
        cols=6,
        rows=6,
        name="t",
        elevation={Hex(1, 1): 2},
        deploy_zones={0: (Hex(0, 0), Hex(1, 0)), 1: (Hex(0, 5),)},
    )
    gs = GameState(
        mapspec=m,
        mission="warzone",
        rng_state=123456789,
        round=2,
        phase="activation",
        phase_index=1,
        initiative=(1, 0),
        active_side=1,
        turn_in_phase=3,
        units={"A1": _sample_unit()},
        terrain={
            Hex(3, 0): TerrainHex(Hex(3, 0), {"blocking", "destructible"}, height=1.5),
            Hex(2, 2): TerrainHex(Hex(2, 2), {"cover"}),
        },
        finished_first_last_round=0,
        pass_tokens={0: 1, 1: 0},
        log_counter=17,
    )
    return gs


def test_gamestate_roundtrip_through_json():
    gs = _sample_state()
    blob = json.dumps(gs.to_dict())
    assert GameState.from_dict(json.loads(blob)) == gs


def test_gamestate_acts_as_visibility_board():
    gs = _sample_state()
    assert gs.blocks_los(Hex(3, 0))
    assert not gs.blocks_los(Hex(2, 2))
    assert gs.is_cover(Hex(2, 2))
    assert gs.column_height(Hex(1, 1)) == 2.0  # elevation, no terrain
    assert gs.column_height(Hex(3, 0)) == 1.5  # terrain height, elevation 0
    # a destroyed building stops blocking
    gs.terrain[Hex(3, 0)].destroyed = True
    assert not gs.blocks_los(Hex(3, 0))


def test_line_of_sight_accepts_gamestate_directly():
    gs = _sample_state()
    res = line_of_sight(gs, Hex(0, 0), Hex(5, 0), VisibilityConfig(mode="strict_center"))
    assert res.blocked_by == Hex(3, 0)
    assert not res.los


def test_unit_at_and_live_units():
    gs = _sample_state()
    assert gs.unit_at(Hex(2, -3)).id == "A1"
    assert gs.unit_at(Hex(9, 9)) is None
    gs.units["A1"].out_of_action = True
    assert gs.live_units() == []
    assert gs.unit_at(Hex(2, -3)) is None


def _mutable_fields_shared(a, b) -> list[str]:
    from dataclasses import fields

    return [
        f.name
        for f in fields(a)
        if isinstance(getattr(a, f.name), (list, dict, set))
        and getattr(a, f.name) is getattr(b, f.name)
    ]


def test_copy_is_independent_and_matches_to_dict():
    from foosim.engine.rules import load
    from foosim.sim.generate import random_setup

    s = random_setup(load(), seed=4)
    c = s.copy()
    assert c.to_dict() == s.to_dict()
    assert c.mapspec is s.mapspec  # intentionally shared (immutable during a game)

    # no mutable container may be shared, at any level (guards new fields being missed)
    assert _mutable_fields_shared(s, c) == []
    for uid, u in s.units.items():
        assert _mutable_fields_shared(u, c.units[uid]) == []
        for w, w2 in zip(u.weapons, c.units[uid].weapons, strict=True):
            assert w is not w2
    for h, t in s.terrain.items():
        assert _mutable_fields_shared(t, c.terrain[h]) == []

    before = s.to_dict()
    unit = next(iter(c.units.values()))
    unit.hp -= 1
    unit.weapons[0].used_this_turn = True
    unit.modifiers["cs"] = 9
    unit.statuses["x"] = 1
    unit.upgrades.append("armor_mk1")
    next(iter(c.terrain.values())).tags.add("cover")
    c.pass_tokens[0] = 5
    assert s.to_dict() == before
