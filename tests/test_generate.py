from foosim.ai.policy import RandomPolicy
from foosim.engine.effects import (
    DEFERRED_SPECIALS,
    DEFERRED_UPGRADE_EFFECTS,
    ammo_supported,
    upgrade_supported,
    weapon_supported,
)
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


def _has_deferred_gear(unit) -> bool:
    for w in unit.weapons:
        if not weapon_supported(RULES.weapon(w.weapon_id)):
            return True
        if w.ammo_id and not ammo_supported(RULES.ammo_spec(w.ammo_id)):
            return True
    return any(not upgrade_supported(RULES.upgrade(uid)) for uid in unit.upgrades)


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


def test_default_generation_never_carries_unimplemented_gear():
    for seed in range(120):
        u = generate_mech(RULES, Rng.from_seed(seed), id="M", side=0)  # supported_only default
        assert not _has_deferred_gear(u), (seed, [w.weapon_id for w in u.weapons], u.upgrades)


def test_full_mode_can_use_the_whole_table():
    seen_deferred = False
    for seed in range(120):
        u = generate_mech(RULES, Rng.from_seed(seed), id="M", side=0, supported_only=False)
        if _has_deferred_gear(u):
            seen_deferred = True
            break
    assert seen_deferred, "supported_only=False should eventually roll deferred gear"


def test_random_setup_default_is_all_supported():
    for seed in range(15):
        gs = random_setup(RULES, seed=seed)
        assert all(not _has_deferred_gear(u) for u in gs.units.values())


def test_effects_classification_covers_generated_content():
    # sanity: the frozensets aren't empty / mislabelled
    assert DEFERRED_SPECIALS and DEFERRED_UPGRADE_EFFECTS
    assert weapon_supported(RULES.weapon("medium_weapon"))
    assert weapon_supported(RULES.weapon("rail_weapon"))  # line_attack now resolved
    assert not weapon_supported(RULES.weapon("large_missile_battery"))  # splash_2in deferred
    assert upgrade_supported(RULES.upgrade("thrusters"))
    assert not upgrade_supported(RULES.upgrade("virus_program"))


def test_call_sign_shape():
    seen = {call_sign(RULES, Rng.from_seed(s)) for s in range(20)}
    assert len(seen) > 1
    assert all(len(name.split(" ")) >= 2 for name in seen)


def test_combat_unit_and_random_setup():
    squad = generate_combat_unit(RULES, Rng.from_seed(3), 0, n=4)
    assert len(squad) == 4
    assert all(u.side == 0 for u in squad)

    gs = random_setup(RULES, seed=5)  # default 4v4
    assert len(gs.units) == 8
    assert sorted(u.side for u in gs.units.values()) == [0, 0, 0, 0, 1, 1, 1, 1]
    positions = [u.pos for u in gs.units.values()]
    assert len(set(positions)) == 8
    assert all(gs.mapspec.in_bounds(p) for p in positions)
    assert not (set(gs.terrain) & set(positions))
    assert gs.mapspec.cols >= 24 and gs.mapspec.rows >= 24  # large board
    assert any("blocking" in t.tags for t in gs.terrain.values())

    small = random_setup(RULES, seed=5, n=2, cols=16, rows=12, terrain="none")
    assert len(small.units) == 4 and small.terrain == {}


def test_random_setup_plays_a_full_game():
    gs = random_setup(RULES, seed=9)
    pols = {0: RandomPolicy(RULES, 1), 1: RandomPolicy(RULES, 2)}
    final, events, _ = run_game(gs, pols, RULES)
    assert final.winner in (0, 1, -1)
    assert any(e.kind == "game_over" for e in events)


def test_squad_is_heavy_leader_two_medium_one_light_with_supported_perk():
    from foosim.engine.effects import perk_supported
    from foosim.sim.generate import generate_squad

    for seed in range(40):
        units, perk = generate_squad(RULES, Rng.from_seed(seed), 0)
        assert [u.profile for u in units] == [
            "mech.heavy", "mech.medium", "mech.medium", "mech.light",
        ]
        assert perk_supported(perk)
        assert all(u.platforms >= 3 for u in units)


def test_random_setup_squads_use_quick_play_makeup():
    gs = random_setup(RULES, seed=2)
    for side in (0, 1):
        frames = sorted(u.profile for u in gs.units.values() if u.side == side)
        assert frames == ["mech.heavy", "mech.light", "mech.medium", "mech.medium"]


def test_pinned_squad_seeds_isolate_variables():
    def sig(gs, side):
        return [(u.profile, u.name, [w.weapon_id for w in u.weapons], u.upgrades, u.speed)
                for u in gs.units.values() if u.side == side]

    a = random_setup(RULES, seed=1, squad_seed_0=77)
    b = random_setup(RULES, seed=2, squad_seed_0=77)
    assert sig(a, 0) == sig(b, 0)          # pinned side identical across game seeds
    assert sig(a, 1) != sig(b, 1)          # the other side still varies
    assert a.terrain.keys() != b.terrain.keys()
    mirror = random_setup(RULES, seed=3, squad_seed_0=5, squad_seed_1=5)
    assert sig(mirror, 0) == sig(mirror, 1)
    pinned_map = random_setup(RULES, seed=4, terrain_seed=9)
    other = random_setup(RULES, seed=5, terrain_seed=9)
    assert pinned_map.terrain.keys() == other.terrain.keys()
    free = random_setup(RULES, seed=1)
    assert sig(free, 0) == sig(random_setup(RULES, seed=1), 0)  # default unchanged
