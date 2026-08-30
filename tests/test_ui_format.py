from foosim.ai.policy import RandomPolicy
from foosim.engine.rules import load
from foosim.sim.autobattle import run_game
from foosim.sim.setups import skirmish_2v2
from foosim.ui import format as fmt

RULES = load()


def _events(seed=1):
    gs = skirmish_2v2(RULES, seed=seed)
    pols = {0: RandomPolicy(RULES, seed * 2 + 1), 1: RandomPolicy(RULES, seed * 2 + 2)}
    _, events, _ = run_game(gs, pols, RULES)
    return events


def test_every_event_formats_to_a_nonempty_string_with_valid_color():
    kinds = set()
    for seed in (1, 2, 20):  # varied outcomes -> broad kind coverage
        for e in _events(seed):
            line = fmt.event_line(e)
            assert isinstance(line, str) and line.strip()
            kinds.add(e.kind)
            r, g, b, a = fmt.event_color(e)
            assert all(0.0 <= c <= 1.0 for c in (r, g, b, a))
    # sanity: we actually exercised the interesting formatters
    for expected in ("attack", "phase_start", "move", "dice_roll", "heat_gain", "game_over"):
        assert expected in kinds


def test_attack_outcome_drives_color():
    hit = type("E", (), {"kind": "attack", "data": {"outcome": "hit"}})()
    crit = type("E", (), {"kind": "attack", "data": {"outcome": "crit"}})()
    miss = type("E", (), {"kind": "attack", "data": {"outcome": "miss"}})()
    assert fmt.event_color(crit) == fmt.event_color(
        type("E", (), {"kind": "critical", "data": {}})()
    )
    assert fmt.event_color(hit) != fmt.event_color(miss)


def test_unit_stat_lines_and_helpers():
    gs = skirmish_2v2(RULES, seed=1)
    u = gs.units["A1"]
    joined = "\n".join(fmt.unit_stat_lines(u))
    assert "HP" in joined and "CS" in joined and "S " in joined
    assert u.id in fmt.unit_label(u) and u.name in fmt.unit_label(u)
    assert 0.0 <= fmt.heat_fraction(u) <= 1.0
    u.heat = 9999
    assert fmt.heat_fraction(u) == 1.0
    u.out_of_action = True
    assert "OUT OF ACTION" in "\n".join(fmt.unit_stat_lines(u))


def test_side_colors_are_distinct():
    assert fmt.side_color(0) != fmt.side_color(1)
    assert fmt.side_color(99) == fmt.NEUTRAL
