import json
import os
from pathlib import Path

import pytest

from foosim.ai.policy import RandomPolicy
from foosim.engine.rules import load
from foosim.engine.state import GameState
from foosim.sim.replay import (
    Replay,
    ReplayError,
    record_game,
    replay_game,
    save,
    state_hash,
)
from foosim.sim.replay import load as load_replay
from foosim.sim.setups import skirmish_2v2

GOLDEN_DIR = Path(__file__).parent / "data" / "replays"
GOLDEN_SEEDS = [1, 2, 20]  # annihilation, side-1 win, side-0 win
REGEN = os.environ.get("FOOSIM_REGEN_GOLDENS") == "1"

RULES = load()


def _setup(seed):
    gs = skirmish_2v2(RULES, seed=seed)
    pols = {0: RandomPolicy(RULES, seed * 2 + 1), 1: RandomPolicy(RULES, seed * 2 + 2)}
    return gs, pols


@pytest.mark.parametrize("seed", [1, 2, 5, 20, 99])
def test_record_then_replay_reproduces_game(seed):
    gs, pols = _setup(seed)
    final, events, rep = record_game(gs, pols, RULES, seed=seed)
    final2, events2 = replay_game(rep, RULES)
    assert state_hash(final) == state_hash(final2)
    assert [e.kind for e in events] == [e.kind for e in events2]
    assert rep.outcome["winner"] == final2.winner
    assert len(rep.decisions) > 0


def test_save_load_roundtrip(tmp_path):
    gs, pols = _setup(7)
    final, _, rep = record_game(gs, pols, RULES, seed=7, label="rt")
    path = tmp_path / "r.json"
    save(rep, path)
    loaded = load_replay(path)
    assert loaded.to_dict() == rep.to_dict()
    final2, _ = replay_game(loaded, RULES)
    assert state_hash(final) == state_hash(final2)


def test_replay_game_uses_default_rules_when_none():
    gs, pols = _setup(3)
    _, _, rep = record_game(gs, pols, RULES, seed=3)
    final, _ = replay_game(rep)  # no rules arg
    assert final.winner == rep.outcome["winner"]


@pytest.mark.parametrize("seed", GOLDEN_SEEDS)
def test_golden_replay_is_stable(seed):
    path = GOLDEN_DIR / f"skirmish_2v2_seed{seed}.json"
    gs, pols = _setup(seed)
    _, _, fresh = record_game(
        gs, pols, RULES, seed=seed, label=f"skirmish_2v2 seed {seed} RandomPolicy"
    )
    if REGEN:
        save(fresh, path)
        pytest.skip(f"regenerated {path.name}")
    golden = load_replay(path)
    assert fresh.ruleset_hash == golden.ruleset_hash, "rules.toml changed - regenerate goldens"
    assert fresh.decisions == golden.decisions
    assert fresh.outcome == golden.outcome
    final, _ = replay_game(golden, RULES)
    assert final.winner == golden.outcome["winner"]


def test_strict_replay_detects_truncated_decisions():
    golden = load_replay(GOLDEN_DIR / "skirmish_2v2_seed1.json")
    chopped = Replay.from_dict({**golden.to_dict(), "decisions": golden.decisions[:-5]})
    with pytest.raises(ReplayError):
        replay_game(chopped, RULES)


def test_strict_replay_detects_leftover_decisions():
    golden = load_replay(GOLDEN_DIR / "skirmish_2v2_seed1.json")
    extra = golden.decisions + [{"kind": "EndActivation"}]
    with pytest.raises(ReplayError):
        replay_game(Replay.from_dict({**golden.to_dict(), "decisions": extra}), RULES)


def test_strict_replay_detects_outcome_mismatch():
    golden = load_replay(GOLDEN_DIR / "skirmish_2v2_seed2.json")
    tampered = Replay.from_dict(
        {**golden.to_dict(), "outcome": {**golden.outcome, "winner": 999}}
    )
    with pytest.raises(ReplayError):
        replay_game(tampered, RULES)


def test_counterfactual_rules_replays_non_strict_without_crashing():
    golden = load_replay(GOLDEN_DIR / "skirmish_2v2_seed20.json")
    harsher = RULES.with_overrides({"to_hit.long_range_inches": 3, "heat.second_action": 2})
    final, events = replay_game(golden, harsher, strict=False)
    assert isinstance(final, GameState)
    assert isinstance(events, list)


def test_replay_is_itself_deterministic():
    golden = load_replay(GOLDEN_DIR / "skirmish_2v2_seed2.json")
    f1, e1 = replay_game(golden, RULES)
    f2, e2 = replay_game(golden, RULES)
    assert state_hash(f1) == state_hash(f2)
    assert [e.kind for e in e1] == [e.kind for e in e2]


def test_decisions_are_json_primitive():
    gs, pols = _setup(11)
    _, _, rep = record_game(gs, pols, RULES, seed=11)
    json.dumps(rep.to_dict())  # must not raise
