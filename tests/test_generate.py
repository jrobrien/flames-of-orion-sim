from foosim.ai.policy import RandomPolicy
from foosim.engine.rng import Rng
from foosim.engine.rules import load
from foosim.sim.autobattle import run_game
from foosim.sim.generate import (
    call_sign,
    generate_combat_unit,
    generate_mech,
    random_setup,
)

RULES = load()


def _pf_used(unit, rules):
    used = sum(int(rules.weapon(w.weapon_id).get("platform_slots", 1)) for w in unit.weapons)
    used += sum(
        1 for uid in unit.upgrades if not rules.upgrade(uid).get("effect", {}).get("free_slot")
    )
    return used


def test_generated_mech_respects_platform_slots():
    for seed in range(30):
        u = generate_mech(RULES, Rng.from_seed(seed), id="M", side=0)
        assert u.profile.startswith("mech.")
        assert u.weapons or u.upgrades
        assert _pf_used(u, RULES) <= u.platforms
        assert u.hp == u.hp_max
        assert " " in u.name  # "<A> <B>" call sign


def test_generation_is_deterministic_per_seed():
    a = generate_mech(RULES, Rng.from_seed(7), id="M", side=0)
    b = generate_mech(RULES, Rng.from_seed(7), id="M", side=0)
    assert a.to_dict() == b.to_dict()


def test_upgrades_are_baked_into_stats():
    # find a seed whose mech took Armor Mk II (set_armor 4) or Thrusters
    for seed in range(200):
        u = generate_mech(RULES, Rng.from_seed(seed), id="M", side=0)
        if "armor_mk2" in u.upgrades:
            assert u.ar == 4
            return
        if u.upgrades.count("thrusters"):
            base = RULES.frame(u.profile.split(".")[1])["speed"]
            assert u.speed == base + u.upgrades.count("thrusters")
            return
    raise AssertionError("no seed produced a stat-baking upgrade in 200 tries")


def test_call_sign_shape():
    seen = {call_sign(RULES, Rng.from_seed(s)) for s in range(20)}
    assert len(seen) > 1
    assert all(len(name.split(" ")) >= 2 for name in seen)


def test_combat_unit_and_random_setup():
    squad = generate_combat_unit(RULES, Rng.from_seed(3), 0, n=4)
    assert len(squad) == 4
    assert all(u.side == 0 for u in squad)

    gs = random_setup(RULES, seed=5)
    assert len(gs.units) == 4
    positions = [u.pos for u in gs.units.values()]
    assert len(set(positions)) == 4
    assert all(gs.mapspec.in_bounds(p) for p in positions)
    assert not (set(gs.terrain) & set(positions))


def test_random_setup_plays_a_full_game():
    gs = random_setup(RULES, seed=9)
    pols = {0: RandomPolicy(RULES, 1), 1: RandomPolicy(RULES, 2)}
    final, events, _ = run_game(gs, pols, RULES)
    assert final.winner in (0, 1, -1)
    assert any(e.kind == "game_over" for e in events)
