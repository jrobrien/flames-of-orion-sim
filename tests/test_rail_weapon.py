"""Rail Weapon: a line attack from the firer through the aim point, hitting every
model (friend or foe) and destructible terrain on the line, +1 self HEAT, stopped
only by indestructible terrain."""

from foosim.engine import resolve
from foosim.engine.actions import RangedAttackAction
from foosim.engine.effects import weapon_supported
from foosim.engine.hexgrid import Hex
from foosim.engine.rules import load
from foosim.engine.state import GameState, MapSpec, TerrainHex
from foosim.sim.setups import mech

RULES = load()


def _field(*specs, terrain=None):
    """specs: (id, side, (q, r)) tuples. First one carries a rail_weapon."""
    units = {}
    for i, (uid, side, (q, r)) in enumerate(specs):
        units[uid] = mech(
            RULES, id=uid, side=side, name=uid, pos=Hex(q, r),
            ranged=("rail_weapon",) if i == 0 else (),
        )
    gs = GameState(mapspec=MapSpec(20, 20), units=units, pass_tokens={0: 0, 1: 0},
                   phase="activation")
    for h, t in (terrain or {}).items():
        gs.terrain[h] = t
    return gs


def _shoot(gs, shooter="A", target="B"):
    return resolve.apply(gs, RangedAttackAction(shooter, target, 0), RULES)


def test_rail_rakes_every_model_between_firer_and_target():
    gs = _field(("A", 0, (0, 0)), ("C", 1, (0, 2)), ("B", 1, (0, 4)))
    _, ev = _shoot(gs)
    hit = {e.data["target"] for e in ev if e.kind == "attack"}
    assert hit == {"B", "C"}  # the in-between model is raked too
    assert any(e.kind == "rail_shot" and e.data["unit"] == "A" for e in ev)


def test_rail_hits_friendlies():
    gs = _field(("A", 0, (0, 0)), ("F", 0, (0, 2)), ("B", 1, (0, 4)))
    _, ev = _shoot(gs)
    assert {e.data["target"] for e in ev if e.kind == "attack"} == {"F", "B"}


def test_rail_self_heat_on_use():
    gs = _field(("A", 0, (0, 0)), ("B", 1, (0, 4)))
    before = gs.units["A"].heat
    ns, ev = _shoot(gs)
    assert ns.units["A"].heat == before + 1
    assert any(e.kind == "heat_gain" and e.data["reason"] == "rail_weapon" for e in ev)


def test_rail_is_blocked_by_indestructible_terrain():
    wall = {Hex(0, 3): TerrainHex(Hex(0, 3), {"blocking", "indestructible"}, 2.0)}
    gs = _field(("A", 0, (0, 0)), ("C", 1, (0, 2)), ("D", 1, (0, 5)), terrain=wall)
    _, ev = _shoot(gs, target="C")  # aim at C; the line would carry on toward D
    hit = {e.data["target"] for e in ev if e.kind == "attack"}
    assert hit == {"C"}  # D is behind the wall
    assert any(e.kind == "rail_blocked" for e in ev)


def test_rail_levels_destructible_terrain_on_the_line_and_ignores_downstream_los():
    cover = {Hex(0, 3): TerrainHex(Hex(0, 3), {"cover", "destructible"}, 0.5)}
    gs = _field(("A", 0, (0, 0)), ("B", 1, (0, 2)), ("C", 1, (0, 4)), terrain=cover)
    ns, ev = _shoot(gs, target="B")
    # C sits behind low cover with no direct LOS, but the rail needs LOS only to B
    assert {e.data["target"] for e in ev if e.kind == "attack"} == {"B", "C"}
    assert ns.terrain[Hex(0, 3)].destroyed
    assert any(e.kind == "terrain_destroyed" for e in ev)


def test_rail_weapon_is_supported_content():
    assert weapon_supported(RULES.weapon("rail_weapon"))
