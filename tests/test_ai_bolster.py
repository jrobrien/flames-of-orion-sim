"""Bolstered actions must be reachable by the AI (table play bolsters constantly)."""

from _helpers import duel
from foosim.ai.policy import RandomPolicy
from foosim.engine.hexgrid import Hex
from foosim.engine.legal import legal_actions
from foosim.engine.rules import load
from foosim.sim.autobattle import run_game
from foosim.sim.setups import skirmish_2v2

RULES = load()


def _activating(seed=1):
    """A GameState mid-activation with a unit that has enemies in range."""
    gs = duel(RULES, b_pos=Hex(1, 0))  # B adjacent to A -> melee + engaged
    gs.units["A"].heat = 0
    gs.phase = "activation"
    gs.activating_unit = "A"
    return gs


def test_legal_actions_includes_bolstered_variants():
    gs = _activating()
    with_b = legal_actions(gs, gs.units["A"], RULES, bolster=True)
    without_b = legal_actions(gs, gs.units["A"], RULES, bolster=False)
    assert all(getattr(a, "bolster", None) is None for a in without_b)
    subs = {a.bolster for a in with_b if getattr(a, "bolster", None)}
    assert "focused_strike" in subs
    assert "fury" in subs or "ram" in subs
    assert len(with_b) > len(without_b)


def test_reboot_only_offered_as_first_action():
    gs = _activating()
    gs.units["A"].heat = 4
    gs.actions_taken = 0
    assert any(getattr(a, "bolster", None) == "reboot"
               for a in legal_actions(gs, gs.units["A"], RULES))
    gs.actions_taken = 1
    assert not any(getattr(a, "bolster", None) == "reboot"
                   for a in legal_actions(gs, gs.units["A"], RULES))


def test_bias_zero_never_bolsters_bias_one_bolsters_with_headroom():
    gs = _activating()
    gs.units["A"].heat = 0  # lots of headroom
    gs.actions_taken = 0

    never = RandomPolicy(RULES, seed=1, bolster_bias=0.0)
    always = RandomPolicy(RULES, seed=1, bolster_bias=1.0)
    # sample many decisions from the same state
    n_never = sum(1 for _ in range(200)
                  if getattr(never.decide(gs), "bolster", None))
    n_always = sum(1 for _ in range(200)
                   if getattr(always.decide(gs), "bolster", None))
    assert n_never == 0
    assert n_always > 100


def test_bias_backs_off_near_overheat():
    gs = _activating()
    gs.units["A"].heat = gs.units["A"].heat_limit - 1  # no headroom
    gs.actions_taken = 1
    pol = RandomPolicy(RULES, seed=1, bolster_bias=1.0)
    assert sum(1 for _ in range(200) if getattr(pol.decide(gs), "bolster", None)) == 0


def test_autobattle_now_uses_bolstered_actions():
    total_bolstered = 0
    for seed in range(1, 11):
        gs = skirmish_2v2(RULES, seed=seed)
        pols = {0: RandomPolicy(RULES, seed * 2 + 1), 1: RandomPolicy(RULES, seed * 2 + 2)}
        _, events, _ = run_game(gs, pols, RULES)
        total_bolstered += sum(
            1 for e in events if e.kind == "heat_gain" and e.data.get("reason") == "activation"
        )
    assert total_bolstered > 0  # activation heat happens => 2nd/bolstered actions occur


def test_autobattle_stays_deterministic_with_bolster():
    def run():
        gs = skirmish_2v2(RULES, seed=4)
        pols = {0: RandomPolicy(RULES, 9), 1: RandomPolicy(RULES, 10)}
        f, e, _ = run_game(gs, pols, RULES)
        return f.winner, tuple(x.kind for x in e)

    assert run() == run()
