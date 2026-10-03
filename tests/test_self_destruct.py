"""Self Destruct upgrade: legal at 7+ HEAT, a guaranteed blast booked to the synthetic
``self_destruct`` weapon (separate from a mech's death ``explosion``), and the
Greedy bot's trigger (HP <= 2, 2+ enemies in the blast, no friendlies)."""

from foosim.ai.policy import GreedyPolicy
from foosim.engine import resolve
from foosim.engine.actions import SelfDestructAction
from foosim.engine.effects import upgrade_supported
from foosim.engine.hexgrid import Hex
from foosim.engine.legal import legal_actions
from foosim.engine.rules import load
from foosim.engine.state import GameState, MapSpec
from foosim.sim.setups import mech

RULES = load()


def _field(specs, *, heat=8, hp=2):
    """specs: (id, side, (q, r)). The first unit carries Self Destruct."""
    units = {}
    for uid, side, (q, r) in specs:
        units[uid] = mech(RULES, id=uid, side=side, name=uid, pos=Hex(q, r))
    sd = units[specs[0][0]]
    sd.upgrades = ["self_destruct"]
    sd.heat, sd.hp = heat, hp
    gs = GameState(mapspec=MapSpec(20, 20), units=units, pass_tokens={0: 0, 1: 0},
                   phase="activation", activating_unit=sd.id)
    return gs, sd


def test_self_destruct_is_supported_and_legal_only_at_threshold():
    assert upgrade_supported(RULES.upgrade("self_destruct"))
    gs, sd = _field([("A", 0, (0, 0)), ("B", 1, (0, 3))], heat=6)
    assert not any(isinstance(a, SelfDestructAction) for a in legal_actions(gs, sd, RULES))
    sd.heat = 7
    assert any(isinstance(a, SelfDestructAction) for a in legal_actions(gs, sd, RULES))


def test_blast_is_guaranteed_and_booked_to_self_destruct_weapon():
    gs, sd = _field([("A", 0, (0, 0)), ("B", 1, (0, 3)), ("C", 1, (2, 3)), ("F", 0, (3, 0))],
                    heat=8)
    new, ev = resolve.apply(gs, SelfDestructAction("A"), RULES)
    assert new.units["A"].out_of_action
    assert any(e.kind == "self_destruct" for e in ev)
    assert not any(e.kind == "explode_check" for e in ev)  # no 1-2 "just dies" roll
    dmg = [e for e in ev if e.kind == "damage"]
    assert dmg and all(e.data["weapon"] == "self_destruct" for e in dmg)
    assert all(e.data["dealer"] == "A" and e.data["cause"] == "explosion" for e in dmg)
    # only the teammate caught in the blast is flagged friendly (excluded from metrics)
    assert {e.data["target"] for e in dmg} == {"B", "C", "F"}
    assert all(e.data["friendly"] == (e.data["target"] == "F") for e in dmg)


def test_death_explosion_uses_the_separate_explosion_weapon():
    gs, sd = _field([("A", 0, (0, 0)), ("B", 1, (0, 3))], heat=0, hp=6)
    sd.upgrades = []
    for state in range(200):  # find a seed where the post-overheat explode check explodes
        ev: list = []
        trial = gs.copy()
        resolve._gain_heat(trial, trial.units["A"], 12, "test", ev, resolve.Rng(state=state),
                           RULES)
        if any(e.kind == "explosion" for e in ev):
            break
    else:
        raise AssertionError("no exploding seed found")
    assert [e.data["weapon"] for e in ev if e.kind == "explosion"] == ["explosion"]
    dmg = [e for e in ev if e.kind == "damage"]
    assert dmg and all(e.data["weapon"] == "explosion" and e.data["dealer"] == "A" for e in dmg)


def _decide(specs, *, hp=2):
    gs, sd = _field(specs, heat=8, hp=hp)
    return GreedyPolicy(RULES, seed=1).decide(gs)


def test_greedy_self_destructs_when_trigger_met():
    d = _decide([("A", 0, (0, 0)), ("B", 1, (0, 3)), ("C", 1, (2, 3))])
    assert isinstance(d, SelfDestructAction)


def test_greedy_holds_without_two_enemies_a_friendly_in_blast_or_with_hp():
    one_enemy = _decide([("A", 0, (0, 0)), ("B", 1, (0, 3))])
    friend = _decide([("A", 0, (0, 0)), ("B", 1, (0, 3)), ("C", 1, (2, 3)), ("F", 0, (3, 0))])
    healthy = _decide([("A", 0, (0, 0)), ("B", 1, (0, 3)), ("C", 1, (2, 3))], hp=3)
    for d in (one_enemy, friend, healthy):
        assert not isinstance(d, SelfDestructAction)
