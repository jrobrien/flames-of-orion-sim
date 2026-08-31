import pytest

from foosim.engine import missions
from foosim.engine.hexgrid import Hex
from foosim.engine.rules import load
from foosim.engine.state import GameState, MapSpec
from foosim.sim.setups import mech

RULES = load()


def _duel_state(mission="warzone", *, round_=1, a_out=False, b_out=False):
    a = mech(RULES, id="A", side=0, name="A", pos=Hex(0, 0))
    b = mech(RULES, id="B", side=1, name="B", pos=Hex(0, 5))
    a.out_of_action = a_out
    b.out_of_action = b_out
    return GameState(mapspec=MapSpec(8, 8), units={"A": a, "B": b},
                     mission=mission, round=round_, pass_tokens={0: 0, 1: 0})


def test_annihilation_wins_immediately_regardless_of_mission():
    for m in ("warzone", "last_standing", "annihilation"):
        w, reason = missions.resolve_winner(_duel_state(m, b_out=True), RULES)
        assert (w, reason) == (0, "annihilation")


def test_not_over_while_both_sides_alive_and_within_round_limit():
    assert missions.resolve_winner(_duel_state(round_=3), RULES) == (None, None)


def test_warzone_round_limit_counts_models():
    # A has 2, B has 1 -> A wins at the round limit
    a1 = mech(RULES, id="A1", side=0, name="A1", pos=Hex(0, 0))
    a2 = mech(RULES, id="A2", side=0, name="A2", pos=Hex(1, 0))
    b1 = mech(RULES, id="B1", side=1, name="B1", pos=Hex(0, 5))
    gs = GameState(mapspec=MapSpec(8, 8),
                   units={"A1": a1, "A2": a2, "B1": b1},
                   mission="warzone", round=RULES.game["rounds"] + 1,
                   pass_tokens={0: 0, 1: 0})
    assert missions.resolve_winner(gs, RULES) == (0, "round_limit")


def test_warzone_equal_models_is_a_draw():
    gs = _duel_state("warzone", round_=RULES.game["rounds"] + 1)
    assert missions.resolve_winner(gs, RULES) == (-1, "round_limit")


def test_annihilation_mission_draws_at_round_limit():
    gs = _duel_state("annihilation", round_=RULES.game["rounds"] + 1)
    assert missions.resolve_winner(gs, RULES) == (-1, "round_limit")


def test_unknown_mission_falls_back_to_warzone():
    gs = _duel_state("does_not_exist", round_=RULES.game["rounds"] + 1)
    assert missions.resolve_winner(gs, RULES) == (-1, "round_limit")


def test_register_extends_the_table():
    @missions.register("_test_only")
    def _side_one_always(_s, _l, _r):
        return 1

    try:
        gs = _duel_state("_test_only", round_=RULES.game["rounds"] + 1)
        assert missions.resolve_winner(gs, RULES) == (1, "round_limit")
    finally:
        missions.MISSIONS.pop("_test_only", None)


def test_registry_has_the_stateless_missions():
    assert {"warzone", "last_standing", "annihilation"} <= set(missions.MISSIONS)


@pytest.mark.parametrize("m", ["warzone", "last_standing"])
def test_stateless_missions_agree_on_model_count(m):
    gs = _duel_state(m, round_=RULES.game["rounds"] + 1, b_out=False)
    assert missions.resolve_winner(gs, RULES)[1] == "round_limit"
