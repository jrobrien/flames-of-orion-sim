from pathlib import Path

from foosim.ai.policy import RandomPolicy
from foosim.engine.rules import load
from foosim.sim import replay as replaymod
from foosim.sim.autobattle import drive
from foosim.sim.replay import state_hash
from foosim.sim.setups import skirmish_2v2
from foosim.ui.timeline import Timeline

RULES = load()
GOLDEN = Path(__file__).parent / "data" / "replays" / "skirmish_2v2_seed1.json"


def _watch(seed=1):
    gs = skirmish_2v2(RULES, seed=seed)
    pols = {0: RandomPolicy(RULES, seed * 2 + 1), 1: RandomPolicy(RULES, seed * 2 + 2)}
    return Timeline(gs, drive(gs, lambda st, sd: pols[sd].decide(st), RULES))


def _replay_tl():
    rep = replaymod.load(GOLDEN)
    tl = Timeline(rep.state(), replaymod.iter_frames(rep, RULES))
    tl.load_all()
    return tl, rep


def test_frame_zero_is_initial_with_no_events_and_lazy():
    tl = _watch()
    assert tl.cursor == 0
    assert tl.current.index == 0 and tl.current.events == []
    assert tl.loaded_count == 1  # nothing pulled from the source yet
    assert not tl.complete


def test_stepping_forward_pulls_frames_lazily():
    tl = _watch()
    assert tl.step(1) is True
    assert tl.cursor == 1 and tl.loaded_count >= 2
    tl.step(5)
    assert tl.cursor == 6 and tl.loaded_count >= 7


def test_step_back_and_forward_clamp():
    tl = _watch()
    tl.step(4)
    assert tl.step(-99) is True and tl.cursor == 0
    assert tl.step(-1) is False and tl.cursor == 0
    tl.load_all()
    tl.seek(10**9)
    assert tl.cursor == tl.last_index and tl.at_end()
    assert tl.step(1) is False


def test_load_all_defines_a_real_total():
    tl = _watch()
    tl.load_all()
    assert tl.complete
    assert tl.last_index > 10


def test_jump_forward_and_backward_and_miss():
    tl, _ = _replay_tl()
    tl.seek(0)
    assert tl.jump(1, lambda e: e.kind == "phase_start") is True  # -> frame 1
    first_ps = tl.cursor
    assert tl.jump(1, lambda e: e.kind == "phase_start") is True  # a later phase
    assert tl.cursor > first_ps
    assert tl.jump(-1, lambda e: e.kind == "game_start") is True  # game_start is in frame 1
    assert tl.cursor == first_ps
    before = tl.cursor
    assert tl.jump(1, lambda e: e.kind == "nonexistent_kind") is False
    assert tl.cursor == before


def test_replay_timeline_last_frame_matches_replay_game():
    tl, rep = _replay_tl()
    final, _ = replaymod.replay_game(rep, RULES)
    assert state_hash(tl.frame(tl.last_index).state) == state_hash(final)
    assert tl.current is tl.frame(tl.cursor)
