import pytest

from foosim.ai.policy import RandomPolicy
from foosim.engine.actions import ActivateUnit, EndActivation, IllegalAction
from foosim.engine.legal import legal_actions
from foosim.engine.rules import load
from foosim.sim.replay import state_hash
from foosim.sim.setups import skirmish_2v2
from foosim.ui.session import Session

RULES = load()


def _gs(seed=1):
    return skirmish_2v2(RULES, seed=seed)


def _human_decision(sess, take_action=False):
    st = sess.live
    if st.activating_unit is None:
        pending = [
            u for u in st.units.values()
            if u.side == st.active_side and not u.activated and not u.out_of_action
        ]
        return ActivateUnit(pending[0].id)
    if take_action and st.actions_taken == 0:
        acts = legal_actions(st, st.units[st.activating_unit], RULES)
        if acts:
            return acts[0]
    return EndActivation()


def _drive_humans(sess, limit=2000):
    n = 0
    while not sess.complete and n < limit:
        assert sess.waiting_for_human()
        sess.submit(_human_decision(sess, take_action=(n % 3 == 0)))
        n += 1
    assert sess.complete


# -- watch (all AI) --------------------------------------------------------


def test_watch_runs_to_completion_via_advance_one():
    sess = Session(RULES, _gs(3), {0: RandomPolicy(RULES, 7), 1: RandomPolicy(RULES, 8)})
    steps = 0
    while not sess.complete and steps < 5000:
        assert sess.advance_one()
        steps += 1
    assert sess.complete
    assert sess.live.winner in (0, 1, -1)
    assert sess.last_index > 10


def test_watch_is_deterministic():
    def run():
        s = Session(RULES, _gs(3), {0: RandomPolicy(RULES, 7), 1: RandomPolicy(RULES, 8)})
        s.load_all()
        return state_hash(s.live), tuple(k for f in s._frames for k in f.event_kinds())

    assert run() == run()


def test_load_all_refuses_when_a_human_is_present():
    sess = Session(RULES, _gs(1), {0: "human", 1: RandomPolicy(RULES, 2)})
    before = sess.last_index
    sess.load_all()
    assert sess.last_index == before  # no-op


# -- play vs AI ----------------------------------------------------------


def test_play_vs_ai_blocks_on_human_then_completes():
    sess = Session(RULES, _gs(2), {0: "human", 1: RandomPolicy(RULES, 5)})
    assert sess.waiting_for_human()
    assert sess.pending_side() == 0
    assert sess.last_index >= 1  # fast-forwarded past initiative
    _drive_humans(sess)
    assert sess.live.winner in (0, 1, -1)


def test_hotseat_needs_input_from_both_sides():
    sess = Session(RULES, _gs(4), {0: "human", 1: "human"})
    seen_sides = set()
    n = 0
    while not sess.complete and n < 3000:
        seen_sides.add(sess.pending_side())
        sess.submit(_human_decision(sess))
        n += 1
    assert seen_sides == {0, 1}
    assert sess.complete


# -- scrub / rewind ----------------------------------------------------


def test_scrubbing_back_is_view_only_and_blocks_submit():
    sess = Session(RULES, _gs(2), {0: "human", 1: RandomPolicy(RULES, 5)})
    for _ in range(4):
        sess.submit(_human_decision(sess))
    live = sess.last_index
    sess.seek(2)
    assert not sess.at_live()
    assert sess.advance_one() and sess.cursor == 3  # scrubs, does not simulate
    assert sess.last_index == live  # history unchanged
    with pytest.raises(IllegalAction):
        sess.submit(EndActivation())


def test_rewind_truncates_history_and_resumes():
    sess = Session(RULES, _gs(2), {0: "human", 1: RandomPolicy(RULES, 5)})
    for _ in range(6):
        sess.submit(_human_decision(sess))
    sess.seek(3)
    sess.rewind_to_cursor()
    assert sess.last_index >= 3
    assert sess.at_live()
    # game is playable again from the rewound point
    _drive_humans(sess)


def test_submit_rejects_when_not_humans_turn():
    sess = Session(RULES, _gs(1), {0: RandomPolicy(RULES, 1), 1: RandomPolicy(RULES, 2)})
    with pytest.raises(IllegalAction):
        sess.submit(EndActivation())


# -- to_replay -------------------------------------------------------


def test_to_replay_reproduces_the_session():
    from foosim.sim.replay import replay_game

    sess = Session(RULES, _gs(3), {0: "human", 1: RandomPolicy(RULES, 8)})
    _drive_humans(sess)
    rep = sess.to_replay()
    assert rep.ruleset_hash == RULES.content_hash
    assert rep.outcome["winner"] == sess.live.winner
    final, _ = replay_game(rep, RULES, strict=False)
    assert state_hash(final) == state_hash(sess.live)


def test_to_replay_after_rewind_reflects_the_new_line():
    from foosim.sim.replay import replay_game

    sess = Session(RULES, _gs(2), {0: "human", 1: RandomPolicy(RULES, 5)})
    for _ in range(6):
        sess.submit(_human_decision(sess))
    sess.seek(3)
    sess.rewind_to_cursor()
    _drive_humans(sess)
    rep = sess.to_replay()
    final, _ = replay_game(rep, RULES, strict=False)
    assert state_hash(final) == state_hash(sess.live)
