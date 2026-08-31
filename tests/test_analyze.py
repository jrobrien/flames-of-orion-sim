from foosim.ai.policy import GreedyPolicy, RandomPolicy
from foosim.engine.rules import load
from foosim.sim.analyze import (
    GameRow,
    diff,
    loadout_string,
    parse_override,
    read_csv,
    run_many,
    summarize,
    write_csv,
)
from foosim.sim.generate import random_setup
from foosim.sim.setups import skirmish_2v2

RULES = load()


def _mk_pol(rules):
    return lambda s: {0: GreedyPolicy(rules, s * 2 + 1), 1: RandomPolicy(rules, s * 2 + 2)}


def _rows(rules, n=20, seed0=0):
    return run_many(
        lambda s: skirmish_2v2(rules, seed=s), _mk_pol(rules), rules, n=n, seed0=seed0
    )


def test_run_many_shape_and_determinism():
    a = _rows(RULES, 15)
    b = _rows(RULES, 15)
    assert len(a) == 15
    assert [r.seed for r in a] == list(range(15))
    assert [vars(r) for r in a] == [vars(r) for r in b]
    for r in a:
        assert r.winner in (0, 1, -1)
        assert r.rounds <= RULES.game["rounds"]
        assert r.survivors_0 >= 0 and r.survivors_1 >= 0
        assert r.damage_dealt >= 0


def test_loadout_is_recorded_and_varies_on_random_setups():
    # fixed skirmish -> every game the same loadout
    fixed = _rows(RULES, 10)
    assert all(r.loadout_0 == fixed[0].loadout_0 for r in fixed)
    assert "*" in fixed[0].loadout_0  # "weapon_id*count,..."

    gs = random_setup(RULES, seed=1)
    lo = loadout_string(gs, 0)
    assert lo and lo == ",".join(sorted(lo.split(",")))  # canonical order

    varied = run_many(
        lambda s: random_setup(RULES, seed=s), _mk_pol(RULES), RULES, n=12
    )
    assert len({r.loadout_0 for r in varied}) > 1
    assert summarize(varied)["distinct_matchups"] > 1


def test_summary_keys_and_rates():
    s = summarize(_rows(RULES, 30))
    assert s["games"] == 30
    assert s["distinct_matchups"] == 1  # fixed skirmish
    assert abs(s["win_rate_0"] + s["win_rate_1"] + s["draw_rate"] - 1.0) < 1e-9
    assert s["decisive_rate"] == s["win_rate_0"] + s["win_rate_1"]
    for k in ("mean_rounds", "mean_damage", "mean_explosions", "mean_heat_deaths"):
        assert isinstance(s[k], float)


def test_parse_override_coercion():
    assert parse_override("to_hit.long_range_inches=8") == ("to_hit.long_range_inches", 8)
    assert parse_override("visibility.sample_corner_fraction=0.9") == (
        "visibility.sample_corner_fraction", 0.9,
    )
    assert parse_override("visibility.mode=strict_center") == ("visibility.mode", "strict_center")
    assert parse_override("x.y=true") == ("x.y", True)


def test_override_shifts_the_aggregate():
    hot = RULES.with_overrides({"heat.second_action": 3})
    base = summarize(_rows(RULES, 40))
    variant = summarize(_rows(hot, 40))
    assert variant != base
    assert variant["mean_heat_deaths"] > base["mean_heat_deaths"]
    d = diff(base, variant)
    assert d["mean_heat_deaths"] > 0
    assert set(d) <= set(base)


def test_csv_roundtrip(tmp_path):
    rows = _rows(RULES, 12)
    p = tmp_path / "rows.csv"
    write_csv(rows, p)
    back = read_csv(p)
    assert [vars(r) for r in back] == [vars(r) for r in rows]
    assert all(isinstance(r, GameRow) for r in back)
