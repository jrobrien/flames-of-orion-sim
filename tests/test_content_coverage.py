"""Every weapon/ammo/upgrade/catastrophic hook in rules.toml is either handled by
the engine or explicitly deferred. Fails loudly when a new token slips in.

Move a token from DEFERRED_* to HANDLED_* when you wire it up.
"""

from foosim.engine.rules import load

RULES = load()

# -- special tokens the engine currently acts on ------------------------------
HANDLED_SPECIALS = {
    "armor_penetration",
    "ignores_los",
    "ignores_cover",
    "ignores_long_range_penalty",
    "target_heat_1d2_on_hit",
    "half_speed_if_fired",
    "plus1_damage",
    "plus2_damage_and_ap_if_moved",
    "crit_on_5plus",
}

# known gaps - the remaining M7 work
DEFERRED_SPECIALS = {
    # Rail Weapon
    "line_attack", "self_heat_1_on_use", "hits_friendlies",
    "los_initial_target_only", "blocked_by_indestructible",
    "splash_2in",                      # Large Missile Battery
    "no_specialty_ammo",               # Flame Thrower (build constraint)
    "engagement_range_3in",            # Cable Whip
    "burnout_on_1_lose_ap",            # Power Weapon
    "hits_all_within_2in", "push_1in",  # Electric Field
    "push_target_1in_on_hit",          # Piston Gauntlet
    "burnout_on_1_becomes_1dmg",       # Energy Sword
    # ammo
    "target_minus2_speed_until_next_activation",
    "push_target_2in", "collision_1_damage",
    "extra_attack_on_hit_roll_6",
    "target_position_compromised", "self_position_compromised",
    # action-granting upgrades
    "action_self_destruct_at_heat_7", "action_active_camo",
    "action_uplink_position_compromised", "action_infect_once_per_game",
    "repel_within_1in_on_4plus",
}

HANDLED_UPGRADE_EFFECTS = {
    "set_armor", "speed_delta", "cs_delta", "heat_limit_delta",
    "platform_slots_delta", "hull_points_delta", "ignore_first_damage",
    "ignores_terrain_on_move", "heat_check_table",
    "explode_as_heat",                       # resolve: nuclear_core
    "ignores_long_range_penalty",            # resolve: long_range_targeting
    "crit_bonus_damage",                     # resolve: sensor_array
    "cs_delta_vs_hot_target", "hot_threshold",  # resolve: thermal_imaging
    "enemy_ranged_cs_penalty",               # resolve: active_camo status
}
DEFERRED_UPGRADE_EFFECTS = {
    "free_slot",                     # generator PF accounting
    "negate_ranged_crit_bonus_damage",  # counter_missiles
}


def _all_specials():
    tokens = set()
    for key in ("ranged_weapons", "melee_weapons", "ammo", "upgrades"):
        for entry in RULES.raw.get(key, []):
            tokens.update(entry.get("special", []))
    return tokens


def test_every_special_token_is_handled_or_deferred():
    unknown = _all_specials() - HANDLED_SPECIALS - DEFERRED_SPECIALS
    assert not unknown, f"unclassified special tokens: {sorted(unknown)}"


def test_handled_and_deferred_specials_do_not_overlap():
    assert not (HANDLED_SPECIALS & DEFERRED_SPECIALS)


def test_every_upgrade_effect_key_is_handled_or_deferred():
    keys = set()
    for up in RULES.raw["upgrades"]:
        keys.update(up.get("effect", {}))
    unknown = keys - HANDLED_UPGRADE_EFFECTS - DEFERRED_UPGRADE_EFFECTS
    assert not unknown, f"unclassified upgrade effect keys: {sorted(unknown)}"


def test_catastrophic_effect_tokens_all_parse():
    from foosim.engine import resolve
    from foosim.engine.rng import Rng
    from foosim.sim.setups import skirmish_2v2

    gs = skirmish_2v2(RULES, seed=1)
    victim = gs.units["B1"]
    for roll in range(2, 13):
        cat = RULES.catastrophic(roll)
        ev: list = []
        # must not raise, must not emit an 'unhandled_effect'
        resolve._apply_catastrophic(gs, victim, cat, RULES, Rng.from_seed(roll), ev)
        assert not any(e.kind == "unhandled_effect" for e in ev), (roll, cat)
