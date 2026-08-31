from foosim.ai.policy import GreedyPolicy, RandomPolicy
from foosim.engine.rules import load
from foosim.sim.autobattle import run_game
from foosim.sim.generate import random_setup
from foosim.sim.replay import state_hash
from foosim.sim.setups import skirmish_2v2

RULES = load()


def _match(seed, p0, p1):
    gs = skirmish_2v2(RULES, seed=seed)
    final, events, _ = run_game(gs, {0: p0, 1: p1}, RULES)
    return final, events


def test_greedy_beats_random_from_either_side():
    greedy_wins = random_wins = 0
    for seed in range(40):
        f, _ = _match(seed, GreedyPolicy(RULES, seed * 2 + 1), RandomPolicy(RULES, seed * 2 + 2))
        greedy_wins += f.winner == 0
        random_wins += f.winner == 1
        f, _ = _match(seed, RandomPolicy(RULES, seed * 2 + 1), GreedyPolicy(RULES, seed * 2 + 2))
        greedy_wins += f.winner == 1
        random_wins += f.winner == 0
    assert greedy_wins > random_wins * 3, (greedy_wins, random_wins)


def test_greedy_is_deterministic():
    a = _match(7, GreedyPolicy(RULES, 1), GreedyPolicy(RULES, 2))
    b = _match(7, GreedyPolicy(RULES, 1), GreedyPolicy(RULES, 2))
    assert state_hash(a[0]) == state_hash(b[0])
    assert [e.kind for e in a[1]] == [e.kind for e in b[1]]


def test_greedy_completes_on_random_setups():
    for seed in range(10):
        pols = {0: GreedyPolicy(RULES, seed + 1), 1: GreedyPolicy(RULES, seed + 2)}
        final, events, steps = run_game(random_setup(RULES, seed=seed), pols, RULES)
        assert final.winner in (0, 1, -1)
        assert 0 < steps < 3000
        assert any(e.kind == "game_over" for e in events)


def test_greedy_bolsters_and_purges():
    kinds = set()
    for seed in range(8):
        _, events = _match(seed, GreedyPolicy(RULES, seed + 1), GreedyPolicy(RULES, seed + 2))
        kinds.update(e.kind for e in events)
    assert "heat_gain" in kinds  # 2nd/bolstered actions happen
    assert "attack" in kinds
