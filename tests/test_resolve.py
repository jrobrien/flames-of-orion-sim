import json

import pytest

from _helpers import duel, rng_state_for_rolls
from foosim.engine import resolve
from foosim.engine.actions import (
    DisengageAction,
    IllegalAction,
    MeleeAttackAction,
    MoveAction,
    PurgeHeatAction,
    RangedAttackAction,
    decision_from_dict,
    decision_to_dict,
)
from foosim.engine.hexgrid import Hex
from foosim.engine.rng import Rng
from foosim.engine.rules import load
from foosim.engine.state import GameState

RULES = load()


def kinds(events):
    return [e.kind for e in events]


def last(events, kind):
    return next(e for e in reversed(events) if e.kind == kind)


# -- movement --------------------------------------------------------------


def test_move_updates_position_and_cost():
    gs = duel(RULES, b_pos=Hex(9, 9))
    s, ev = resolve.apply(gs, MoveAction("A", [Hex(0, 0), Hex(1, 0), Hex(2, 0)]), RULES)
    assert s.units["A"].pos == Hex(2, 0)
    mv = last(ev, "move")
    assert mv.data["cost"] == 2 and mv.data["kind"] == "move"
    assert gs.units["A"].pos == Hex(0, 0)  # original untouched


@pytest.mark.parametrize(
    "path",
    [
        [Hex(0, 0), Hex(2, 0)],  # non-adjacent
        [Hex(0, 0)] + [Hex(i, 0) for i in range(1, 9)],  # exceeds speed 6
        [Hex(1, 0), Hex(2, 0)],  # does not start at unit
    ],
)
def test_illegal_moves_raise(path):
    gs = duel(RULES, b_pos=Hex(9, 9))
    with pytest.raises(IllegalAction):
        resolve.apply(gs, MoveAction("A", path), RULES)


def test_cannot_move_while_engaged():
    gs = duel(RULES, b_pos=Hex(1, 0))
    with pytest.raises(IllegalAction):
        resolve.apply(gs, MoveAction("A", [Hex(0, 0), Hex(0, 1)]), RULES)


def test_cannot_end_on_occupied_hex():
    gs = duel(RULES, b_pos=Hex(3, 0))
    with pytest.raises(IllegalAction):
        resolve.apply(gs, MoveAction("A", [Hex(0, 0), Hex(1, 0), Hex(2, 0), Hex(3, 0)]), RULES)


# -- ranged --------------------------------------------------------------


def test_natural_one_always_misses():
    gs = duel(RULES, rng_state=rng_state_for_rolls([1]))
    s, ev = resolve.apply(gs, RangedAttackAction("A", "B", 0), RULES)
    assert last(ev, "attack").data["outcome"] == "miss"
    assert "damage" not in kinds(ev)
    assert s.units["A"].weapons[0].used_this_turn is True


def test_hit_applies_saves_and_reduces_hp():
    # to-hit 5 (hit, not crit); two save rolls that never save (not 6, < AR 7)
    gs = duel(RULES, rng_state=rng_state_for_rolls([5, 1, 1]), b_over={"ar": 7})
    s, ev = resolve.apply(gs, RangedAttackAction("A", "B", 0), RULES)
    atk = last(ev, "attack")
    assert atk.data["outcome"] == "hit"
    dmg = last(ev, "damage")
    assert dmg.data["amount"] == 2  # medium weapon
    assert s.units["B"].hp == s.units["B"].hp_max - 2


def test_crit_confirms_catastrophic_cockpit_fire():
    # to-hit 6 -> crit; confirm 6 (>= CS 4); table 6+6 = 12 Cockpit Fire; explode check 1 -> no boom
    gs = duel(RULES, rng_state=rng_state_for_rolls([6, 6, 6, 6, 1]))
    s, ev = resolve.apply(gs, RangedAttackAction("A", "B", 0), RULES)
    assert "critical" in kinds(ev)
    cat = last(ev, "catastrophic")
    assert cat.data["result_name"] == "Cockpit Fire"
    assert "explode_check" in kinds(ev)
    assert s.units["B"].out_of_action is True


def test_out_of_range_and_no_los_raise():
    # flame thrower max range 10"; place target 12 hexes away
    gs = duel(RULES, a_ranged=("flame_thrower",), b_pos=Hex(0, 12))
    with pytest.raises(IllegalAction):
        resolve.apply(gs, RangedAttackAction("A", "B", 0), RULES)


def test_snap_shot_moves_then_fires_at_minus_one_cs():
    gs = duel(RULES, a_pos=Hex(0, 0), b_pos=Hex(0, 8),
              rng_state=rng_state_for_rolls([5, 1, 1]), b_over={"ar": 7})
    path = [Hex(0, i) for i in range(4)]  # move 3 toward B
    s, ev = resolve.apply(gs, MoveAction("A", path, bolster="snap_shot", shot_target="B"), RULES)
    kinds = [e.kind for e in ev]
    assert kinds[:2] == ["move", "snap_shot"]
    atk = last(ev, "attack")
    assert atk.data["effective_cs"] == gs.units["A"].cs + 1  # -1 CS = harder
    assert s.units["A"].pos == Hex(0, 3)  # finished the move
    assert s.units["A"].weapons[0].used_this_turn


# -- heat / explode ------------------------------------------------------


def test_gain_heat_to_limit_triggers_explode():
    gs = duel(RULES, rng_state=rng_state_for_rolls([3]))  # explode-check d6 = 3 -> boom
    u = gs.units["A"]
    u.heat = u.heat_limit - 1
    rng = Rng(state=gs.rng_state)
    ev = []
    resolve._gain_heat(gs, u, 1, "test", ev, rng, RULES)
    assert "overheat" in kinds(ev)
    ec = last(ev, "explode_check")
    assert ec.data["exploded"] is True
    assert "explosion" in kinds(ev)
    assert u.out_of_action is True


def test_explosion_damages_adjacent_unit():
    gs = duel(
        RULES,
        b_pos=Hex(1, 0),
        rng_state=rng_state_for_rolls([3, 1, 1, 1, 1]),
        b_over={"ar": 7},
    )
    a = gs.units["A"]
    a.heat = 8
    rng = Rng(state=gs.rng_state)
    ev = []
    resolve._explode_check(gs, a, rng, RULES, ev, cause="test")
    exp = last(ev, "explosion")
    assert exp.data["affected"] == ["B"]
    assert gs.units["B"].hp == gs.units["B"].hp_max - 4  # floor(8/2)
    assert a.out_of_action is True


# -- disengage / purge -------------------------------------------------


def test_disengage_provokes_free_attack():
    gs = duel(RULES, b_pos=Hex(1, 0), b_melee=("close_combat_weapon",))
    _, ev = resolve.apply(gs, DisengageAction("A", [Hex(0, 0), Hex(0, 1)]), RULES)
    assert "free_attack" in kinds(ev)
    assert gs.units["A"].pos == Hex(0, 0)


def test_dodge_avoids_free_attack():
    gs = duel(RULES, b_pos=Hex(1, 0), b_melee=("close_combat_weapon",))
    s, ev = resolve.apply(gs, DisengageAction("A", [Hex(0, 0), Hex(0, 1)], bolster="dodge"), RULES)
    assert "free_attack" not in kinds(ev)
    assert s.units["A"].pos == Hex(0, 1)


def test_purge_reduces_heat_and_sets_position_compromised():
    gs = duel(RULES)
    gs.units["A"].heat = 5
    s, ev = resolve.apply(gs, PurgeHeatAction("A"), RULES)
    assert s.units["A"].heat < 5
    assert s.units["A"].statuses.get("position_compromised") == 1
    assert last(ev, "heat_purge").data["mode"] == "purge"


def test_reboot_must_be_only_action():
    gs = duel(RULES)
    gs.actions_taken = 1
    with pytest.raises(IllegalAction):
        resolve.apply(gs, PurgeHeatAction("A", bolster="reboot"), RULES)


def test_position_compromised_gives_attacker_bonus_then_clears():
    gs = duel(RULES, rng_state=rng_state_for_rolls([4, 6]), b_over={"ar": 2})
    gs.units["B"].statuses["position_compromised"] = 1
    s, ev = resolve.apply(gs, RangedAttackAction("A", "B", 0), RULES)
    atk = last(ev, "attack")
    assert atk.data["position_compromised"] is True
    assert atk.data["effective_cs"] == gs.units["A"].cs - 1
    assert "position_compromised" not in s.units["B"].statuses


# -- serialization --------------------------------------------------


def test_decision_roundtrip():
    for d in (
        MoveAction("A", [Hex(0, 0), Hex(1, 0)], bolster="run"),
        RangedAttackAction("A", "B", 1, bolster="focused_fire"),
        MeleeAttackAction("A", "B", 0, bolster="ram"),
        DisengageAction("A", [Hex(0, 0), Hex(0, 1)]),
        PurgeHeatAction("A", bolster="reboot"),
    ):
        assert decision_from_dict(json.loads(json.dumps(decision_to_dict(d)))) == d


def test_apply_does_not_mutate_input_state():
    gs = duel(RULES, rng_state=rng_state_for_rolls([5, 1, 1]), b_over={"ar": 7})
    snap = json.dumps(gs.to_dict(), sort_keys=True)
    resolve.apply(gs, RangedAttackAction("A", "B", 0), RULES)
    assert json.dumps(gs.to_dict(), sort_keys=True) == snap


def test_apply_advances_rng_state():
    gs = duel(RULES, rng_state=12345)
    s, _ = resolve.apply(gs, RangedAttackAction("A", "B", 0), RULES)
    assert s.rng_state != gs.rng_state
    assert isinstance(s, GameState)
