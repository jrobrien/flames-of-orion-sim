from foosim.engine import resolve
from foosim.engine.hexgrid import Hex, from_offset_oddr
from foosim.engine.rules import load
from foosim.sim.setups import mech, skirmish_2v2
from foosim.ui.interaction import Overlay, compute_overlay, submode

RULES = load()


def test_submode_mapping():
    assert submode("targeting_move", True) == "run"
    assert submode("targeting_ranged", True) == "focused_fire"
    assert submode("targeting_melee", False) is None
    assert submode("idle", True) is None


def test_idle_when_no_unit_or_unknown_mode():
    gs = skirmish_2v2(RULES, terrain="none")
    assert compute_overlay(gs, RULES, "idle", "A1", None, False).mode == "idle"
    assert compute_overlay(gs, RULES, "targeting_move", None, None, False).mode == "idle"
    assert compute_overlay(gs, RULES, "bogus", "A1", None, False).mode == "idle"


def test_move_overlay_lists_reachable_paths():
    gs = skirmish_2v2(RULES, terrain="none")
    gs.units["A1"].pos = from_offset_oddr(8, 6)  # centre of the 16x12 board
    ov = compute_overlay(gs, RULES, "targeting_move", "A1", None, False)
    assert ov.mode == "targeting_move"
    assert ov.reachable
    u = gs.units["A1"]
    for dest, path in ov.reachable.items():
        assert path[0] == u.pos and path[-1] == dest
        assert len(path) - 1 <= u.stat("speed")
    # 'run' bolster reaches further (+3")
    run = compute_overlay(gs, RULES, "targeting_move", "A1", None, True)
    assert len(run.reachable) > len(ov.reachable)


def test_disengage_overlay_uses_half_speed():
    a = mech(RULES, id="A", side=0, name="A", pos=from_offset_oddr(4, 4))
    b = mech(RULES, id="B", side=1, name="B", pos=from_offset_oddr(5, 4))  # adjacent
    from foosim.engine.state import GameState, MapSpec

    gs = GameState(mapspec=MapSpec(12, 12), units={"A": a, "B": b}, pass_tokens={0: 0, 1: 0})
    ov = compute_overlay(gs, RULES, "targeting_disengage", "A", None, False)
    for path in ov.reachable.values():
        assert len(path) - 1 <= a.stat("speed") // 2


def test_attack_overlay_targets_are_plan_legal():
    gs = skirmish_2v2(RULES, seed=1, terrain="none")
    # move A1 next to a B unit so melee has a target and ranged has LOS
    gs.units["A1"].pos = Hex(gs.units["B1"].pos.q, gs.units["B1"].pos.r - 2)
    r = compute_overlay(gs, RULES, "targeting_ranged", "A1", 0, False)
    m = compute_overlay(gs, RULES, "targeting_melee", "A1", 1, False)
    for tid in r.targets:
        assert resolve.plan_attack(gs, "A1", tid, 0, RULES, kind="ranged").legal
    # ranged should see at least one enemy on the open board
    assert r.targets
    assert isinstance(m, Overlay)


def test_overlay_helpers():
    gs = skirmish_2v2(RULES, terrain="none")
    ov = compute_overlay(gs, RULES, "targeting_move", "A1", None, False)
    some_dest = next(iter(ov.reachable))
    assert ov.is_valid_dest(some_dest)
    assert not ov.is_valid_dest(Hex(999, 999))
