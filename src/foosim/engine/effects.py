"""What the engine actually implements, as data.

Two consumers:
* ``test_content_coverage`` - every token in ``rules.toml`` must be classified
  here (``HANDLED`` or ``DEFERRED``); a new one fails the suite.
* ``sim.generate`` - by default it only rolls fully-supported equipment, so
  random mechs don't carry inert gear (see PLAN.md M7c backlog).

Move a token from ``DEFERRED_*`` to ``HANDLED_*`` the moment you wire it up.
"""

from __future__ import annotations

__all__ = [
    "DEFERRED_SPECIALS",
    "DEFERRED_UPGRADE_EFFECTS",
    "HANDLED_SPECIALS",
    "HANDLED_UPGRADE_EFFECTS",
    "ammo_supported",
    "upgrade_supported",
    "weapon_supported",
]

# `special` tokens the resolver (or, for build constraints, the generator) acts on
HANDLED_SPECIALS = frozenset({
    "armor_penetration",
    "ignores_los",
    "ignores_cover",
    "ignores_long_range_penalty",
    "target_heat_1d2_on_hit",
    "half_speed_if_fired",
    "no_specialty_ammo",  # generator honours it (no ammo assigned)
    "plus1_damage",
    "plus2_damage_and_ap_if_moved",
    "crit_on_5plus",
})

# not yet implemented - the M7c backlog
DEFERRED_SPECIALS = frozenset({
    # Rail Weapon
    "line_attack", "self_heat_1_on_use", "hits_friendlies",
    "los_initial_target_only", "blocked_by_indestructible",
    "splash_2in",                      # Large Missile Battery
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
})

HANDLED_UPGRADE_EFFECTS = frozenset({
    "set_armor", "speed_delta", "cs_delta", "heat_limit_delta",
    "platform_slots_delta", "hull_points_delta", "ignore_first_damage",
    "ignores_terrain_on_move", "heat_check_table", "free_slot",
    "explode_as_heat",                       # resolve: nuclear_core
    "ignores_long_range_penalty",            # resolve: long_range_targeting
    "crit_bonus_damage",                     # resolve: sensor_array
    "cs_delta_vs_hot_target", "hot_threshold",  # resolve: thermal_imaging
    "enemy_ranged_cs_penalty",  # resolve reads it, but only under the (deferred) camo action
})

DEFERRED_UPGRADE_EFFECTS = frozenset({
    "negate_ranged_crit_bonus_damage",  # counter_missiles
})


def _specials(spec: dict) -> set[str]:
    return set(spec.get("special", []))


def weapon_supported(wspec: dict) -> bool:
    return _specials(wspec) <= HANDLED_SPECIALS


def ammo_supported(aspec: dict) -> bool:
    return _specials(aspec) <= HANDLED_SPECIALS


def upgrade_supported(uspec: dict) -> bool:
    if not _specials(uspec) <= HANDLED_SPECIALS:
        return False
    return set(uspec.get("effect", {})) <= HANDLED_UPGRADE_EFFECTS
