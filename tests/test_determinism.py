"""The engine must be bit-reproducible: same initial state + decisions -> same game."""

import pytest

from foosim.ai.policy import RandomPolicy
from foosim.engine.rules import load
from foosim.sim.autobattle import run_game
from foosim.sim.replay import state_hash
from foosim.sim.setups import skirmish_2v2

RULES = load()


def _play(seed):
    gs = skirmish_2v2(RULES, seed=seed)
    pols = {0: RandomPolicy(RULES, seed * 2 + 1), 1: RandomPolicy(RULES, seed * 2 + 2)}
    final, events, steps = run_game(gs, pols, RULES)
    return state_hash(final), tuple(e.kind for e in events), final.winner, steps


@pytest.mark.parametrize("seed", range(50))
def test_same_seed_same_game(seed):
    a = _play(seed)
    b = _play(seed)
    assert a == b


def test_distinct_seeds_produce_distinct_games():
    hashes = {_play(seed)[0] for seed in range(1, 13)}
    assert len(hashes) > 1


def test_run_game_and_records_agree():
    from foosim.sim.replay import record_game, replay_game

    for seed in (1, 2, 20, 77):
        gs = skirmish_2v2(RULES, seed=seed)
        pols = {0: RandomPolicy(RULES, seed * 2 + 1), 1: RandomPolicy(RULES, seed * 2 + 2)}
        via_run, _, _ = run_game(gs, pols, RULES)

        gs2 = skirmish_2v2(RULES, seed=seed)
        pols2 = {0: RandomPolicy(RULES, seed * 2 + 1), 1: RandomPolicy(RULES, seed * 2 + 2)}
        _, _, rep = record_game(gs2, pols2, RULES, seed=seed)
        via_replay, _ = replay_game(rep, RULES)

        assert state_hash(via_run) == state_hash(via_replay)
