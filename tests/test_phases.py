import json

import pytest

from _helpers import rng_state_for_rolls
from foosim.ai.policy import RandomPolicy
from foosim.engine import phases
from foosim.engine.rules import load
from foosim.engine.state import GameState, MapSpec
from foosim.sim.autobattle import run_game
from foosim.sim.setups import mech, skirmish_2v2

RULES = load()


def _play(rules, seed):
    gs = skirmish_2v2(rules, seed=seed)
    pols = {0: RandomPolicy(rules, seed * 2 + 1), 1: RandomPolicy(rules, seed * 2 + 2)}
    return run_game(gs, pols, rules)


@pytest.mark.parametrize("seed", range(1, 21))
def test_random_2v2_completes(seed):
    final, events, steps = _play(RULES, seed)
    assert final.phase == "done"
    assert final.winner in (0, 1, -1)
    assert final.round <= RULES.game["rounds"] + 1
    assert 0 < steps < 2000
    assert any(e.kind == "game_over" for e in events)


def test_determinism_state_and_events():
    for seed in (1, 7, 42):
        f1, e1, s1 = _play(RULES, seed)
        f2, e2, s2 = _play(RULES, seed)
        assert s1 == s2
        assert json.dumps(f1.to_dict(), sort_keys=True) == json.dumps(f2.to_dict(), sort_keys=True)
        assert [e.kind for e in e1] == [e.kind for e in e2]


def test_inserting_an_unknown_phase_does_not_break_the_driver():
    r2 = RULES.with_overrides(
        {"game.phase_order": ["initiative", "activation", "bonus_melee", "heat"]}
    )
    final, events, _ = _play(r2, 3)
    assert final.phase == "done"
    assert final.winner in (0, 1, -1)
    skipped = [e for e in events if e.kind == "phase_skipped"]
    assert skipped and all(e.data["phase"] == "bonus_melee" for e in skipped)


def test_annihilation_ends_the_game():
    from foosim.engine.hexgrid import Hex

    a = mech(RULES, id="A", side=0, name="A", pos=Hex(0, 0))
    b = mech(RULES, id="B", side=1, name="B", pos=Hex(0, 3))
    b.out_of_action = True
    gs = GameState(
        mapspec=MapSpec(cols=8, rows=8),
        units={"A": a, "B": b},
        initiative=(0, 1),
        pass_tokens={0: 0, 1: 0},
        phase="setup",
    )
    s, ev = phases.step(gs, None, RULES)
    assert s.winner == 0
    assert s.end_reason == "annihilation"
    assert s.phase == "done"


def test_first_finisher_gets_initiative_bonus_next_round():
    from foosim.engine.hexgrid import Hex

    # both base rolls 3; side 1 finished first last round -> +1 -> side 1 leads
    a = mech(RULES, id="A", side=0, name="A", pos=Hex(0, 0))
    b = mech(RULES, id="B", side=1, name="B", pos=Hex(0, 4))
    gs = GameState(
        mapspec=MapSpec(cols=8, rows=8),
        units={"A": a, "B": b},
        pass_tokens={0: 0, 1: 0},
        phase="initiative",
        rng_state=rng_state_for_rolls([3, 3]),
        finished_first_last_round=1,
    )
    s, ev = phases.step(gs, None, RULES)
    init = next(e for e in ev if e.kind == "initiative")
    assert init.data["rolls"] == {"0": 3, "1": 4}
    assert s.initiative[0] == 1


def test_needs_decision_is_none_outside_activation():
    gs = skirmish_2v2(RULES, seed=1)
    assert phases.needs_decision(gs) is None  # setup
    s, _ = phases.step(gs, None, RULES)  # runs initiative, enters activation
    assert s.phase == "activation"
    assert phases.needs_decision(s) == s.active_side
