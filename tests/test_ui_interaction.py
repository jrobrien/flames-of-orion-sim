from foosim.engine import resolve
from foosim.engine.hexgrid import Hex, from_offset_oddr
from foosim.engine.rules import load
from foosim.engine.state import GameState, MapSpec
from foosim.sim.setups import mech, skirmish_2v2
from foosim.ui.interaction import SUBMODE_LABELS, SUBMODES, Overlay, compute_overlay

RULES = load()


def test_submode_tables_cover_every_option_with_a_label():
    for subs in SUBMODES.values():
        assert subs[0] == ""  # standard first
        for s in subs:
            assert s in SUBMODE_LABELS


def test_idle_when_no_unit_or_unknown_mode():
    gs = skirmish_2v2(RULES, terrain="none")
    assert compute_overlay(gs, RULES, "idle", "A1", None, "").mode == "idle"
    assert compute_overlay(gs, RULES, "targeting_move", None, None, "").mode == "idle"
    assert compute_overlay(gs, RULES, "bogus", "A1", None, "").mode == "idle"


def test_move_overlay_and_run_reaches_further():
    gs = skirmish_2v2(RULES, terrain="none")
    gs.units["A1"].pos = from_offset_oddr(8, 6)
    ov = compute_overlay(gs, RULES, "targeting_move", "A1", None, "")
    u = gs.units["A1"]
    for dest, path in ov.reachable.items():
        assert path[0] == u.pos and path[-1] == dest
        assert len(path) - 1 <= u.stat("speed")
    run = compute_overlay(gs, RULES, "targeting_move", "A1", None, "run")
    assert len(run.reachable) > len(ov.reachable)


def test_charge_overlay_only_hexes_adjacent_to_an_enemy():
    a = mech(RULES, id="A", side=0, name="A", pos=from_offset_oddr(4, 6),
             melee=("close_combat_weapon",))
    b = mech(RULES, id="B", side=1, name="B", pos=from_offset_oddr(9, 6))
    gs = GameState(mapspec=MapSpec(16, 12), units={"A": a, "B": b}, pass_tokens={0: 0, 1: 0})
    ov = compute_overlay(gs, RULES, "targeting_move", "A", None, "charge")
    assert ov.reachable  # can get adjacent to B within speed 6
    for dest in ov.reachable:
        assert dest in ov.charge_targets and ov.charge_targets[dest] == "B"
    # a unit with no melee weapon cannot charge
    a.weapons = []
    assert not compute_overlay(gs, RULES, "targeting_move", "A", None, "charge").reachable


def test_disengage_overlay_uses_half_speed():
    a = mech(RULES, id="A", side=0, name="A", pos=from_offset_oddr(4, 4))
    b = mech(RULES, id="B", side=1, name="B", pos=from_offset_oddr(5, 4))
    gs = GameState(mapspec=MapSpec(12, 12), units={"A": a, "B": b}, pass_tokens={0: 0, 1: 0})
    ov = compute_overlay(gs, RULES, "targeting_disengage", "A", None, "")
    for path in ov.reachable.values():
        assert len(path) - 1 <= a.stat("speed") // 2


def test_attack_overlay_targets_are_plan_legal():
    gs = skirmish_2v2(RULES, seed=1, terrain="none")
    gs.units["A1"].pos = Hex(gs.units["B1"].pos.q, gs.units["B1"].pos.r - 2)
    r = compute_overlay(gs, RULES, "targeting_ranged", "A1", 0, "")
    assert r.targets
    for tid in r.targets:
        assert resolve.plan_attack(gs, "A1", tid, 0, RULES, kind="ranged").legal
    ff = compute_overlay(gs, RULES, "targeting_ranged", "A1", 0, "focused_fire")
    assert ff.targets == r.targets  # same reachability, better odds


def test_ram_overlay_is_adjacent_enemies_only():
    a = mech(RULES, id="A", side=0, name="A", pos=from_offset_oddr(4, 4),
             melee=("close_combat_weapon",))
    b = mech(RULES, id="B", side=1, name="B", pos=from_offset_oddr(5, 4))  # adjacent
    c = mech(RULES, id="C", side=1, name="C", pos=from_offset_oddr(9, 4))  # far
    gs = GameState(mapspec=MapSpec(16, 12), units={"A": a, "B": b, "C": c},
                   pass_tokens={0: 0, 1: 0})
    ov = compute_overlay(gs, RULES, "targeting_melee", "A", 0, "ram")
    assert ov.targets == {"B"}
    a.can_ram = False
    assert compute_overlay(gs, RULES, "targeting_melee", "A", 0, "ram").targets == set()


def test_overlay_helpers():
    gs = skirmish_2v2(RULES, terrain="none")
    ov = compute_overlay(gs, RULES, "targeting_move", "A1", None, "")
    some_dest = next(iter(ov.reachable))
    assert ov.is_valid_dest(some_dest)
    assert not ov.is_valid_dest(Hex(999, 999))
    assert isinstance(ov, Overlay)
