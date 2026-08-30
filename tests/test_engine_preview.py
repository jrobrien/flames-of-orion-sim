from _helpers import duel
from foosim.engine import resolve
from foosim.engine.hexgrid import Hex
from foosim.engine.rules import load
from foosim.engine.state import TerrainHex

RULES = load()


def test_clean_ranged_shot_numbers():
    gs = duel(RULES, b_pos=Hex(0, 3))
    p = resolve.plan_attack(gs, "A", "B", 0, RULES, kind="ranged")
    assert p.legal and p.reason is None
    assert p.effective_cs == 4  # medium frame CS, no modifiers
    assert p.hit_chance == 0.5  # rolls 4,5,6
    assert p.crit_chance == 1 / 6
    assert p.catastrophic_chance == (1 / 6) * (3 / 6)  # confirm >= CS 4 -> {4,5,6}
    assert p.save_tn == 6  # AR 6, no cover, no AP
    assert p.damage_expr == "2"
    assert 0.9 < p.expected_damage_through < 1.05
    assert p.heat_cost == 0


def test_long_range_worsens_cs_and_hit_chance():
    near = resolve.plan_attack(duel(RULES, b_pos=Hex(0, 3)), "A", "B", 0, RULES, kind="ranged")
    far = resolve.plan_attack(duel(RULES, b_pos=Hex(0, 14)), "A", "B", 0, RULES, kind="ranged")
    assert far.long_range and not near.long_range
    assert far.effective_cs == near.effective_cs + 1
    assert far.hit_chance < near.hit_chance


def test_cover_raises_save_tn():
    gs = duel(RULES, b_pos=Hex(0, 4))
    gs.terrain = {Hex(0, 2): TerrainHex(Hex(0, 2), {"cover"})}
    p = resolve.plan_attack(gs, "A", "B", 0, RULES, kind="ranged")
    assert p.legal and p.cover
    assert p.save_tn == 7  # AR 6 + cover 1


def test_illegal_shots_report_reason_and_zero_chance():
    blocked = duel(RULES, b_pos=Hex(0, 4))
    blocked.terrain = {Hex(0, 2): TerrainHex(Hex(0, 2), {"blocking"})}
    p = resolve.plan_attack(blocked, "A", "B", 0, RULES, kind="ranged")
    assert not p.legal and "line of sight" in p.reason
    assert p.hit_chance == 0.0

    engaged = duel(RULES, b_pos=Hex(1, 0))
    assert not resolve.plan_attack(engaged, "A", "B", 0, RULES, kind="ranged").legal

    melee_far = resolve.plan_attack(duel(RULES, b_pos=Hex(0, 5)), "A", "B", 1, RULES, kind="melee")
    assert not melee_far.legal and "reach" in melee_far.reason


def test_position_compromised_folds_into_displayed_cs():
    gs = duel(RULES, b_pos=Hex(0, 3))
    base = resolve.plan_attack(gs, "A", "B", 0, RULES, kind="ranged").effective_cs
    gs.units["B"].statuses["position_compromised"] = 1
    pc = resolve.plan_attack(gs, "A", "B", 0, RULES, kind="ranged")
    assert pc.position_compromised
    assert pc.effective_cs == base - 1


def test_heat_cost_reflects_second_action_and_bolster():
    gs = duel(RULES, b_pos=Hex(0, 3))
    assert resolve.plan_attack(gs, "A", "B", 0, RULES, kind="ranged").heat_cost == 0
    gs.actions_taken = 1
    assert resolve.plan_attack(gs, "A", "B", 0, RULES, kind="ranged").heat_cost == 1
    bolstered = resolve.plan_attack(gs, "A", "B", 0, RULES, kind="ranged", bolster="focused_fire")
    assert bolstered.heat_cost == 2


def test_plan_matches_resolver_effective_cs():
    """The number the preview shows must be the number the resolver rolls against."""
    gs = duel(RULES, b_pos=Hex(0, 14), rng_state=1)  # long range
    plan = resolve.plan_attack(gs, "A", "B", 0, RULES, kind="ranged")
    _, events = resolve.apply(gs, _ranged(gs), RULES)
    atk = next(e for e in events if e.kind == "attack")
    assert atk.data["effective_cs"] == plan.effective_cs
    assert atk.data["long_range"] == plan.long_range


def _ranged(gs):
    from foosim.engine.actions import RangedAttackAction

    return RangedAttackAction("A", "B", 0)
