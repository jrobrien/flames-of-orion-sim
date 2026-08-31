"""Bake an upgrade loadout into a Unit's stats. Used by setups and the generator.

Upgrade ``effect`` dicts in ``rules.toml`` are one of two kinds:

* **stat bake** - applied here, once, at build time (Armor Mk, Thrusters, Heavy
  Plating, Core Stabilizers, Extra Platforms, Targeting System, Reactive Armor,
  Heat Sink, VTOL).
* **resolve-time lookup** - the engine checks ``id in unit.upgrades`` while
  resolving an action (Sensor Array, Nuclear Core, Long Range Targeting, Thermal
  Imaging, Counter Missiles, Camouflage). Nothing to bake; listed in
  ``RESOLVE_TIME_UPGRADES`` for the coverage test.
"""

from __future__ import annotations

from foosim.engine.rules import Ruleset
from foosim.engine.state import Unit

__all__ = ["RESOLVE_TIME_UPGRADES", "apply_upgrades"]

RESOLVE_TIME_UPGRADES = frozenset({
    "sensor_array",
    "nuclear_core",
    "long_range_targeting",
    "thermal_imaging",
    "counter_missiles",
    "camouflage",
    "reactive_armor",  # baked below, but also read at resolve for the "per game" note
})

# upgrades that grant an activation action (not modelled yet - M7 chunk b)
ACTION_UPGRADES = frozenset({"self_destruct", "up_link", "virus_program", "defense_array"})


def apply_upgrades(unit: Unit, rules: Ruleset) -> None:
    for uid in unit.upgrades:
        eff = rules.upgrade(uid).get("effect", {})
        if "set_armor" in eff:
            unit.ar = int(eff["set_armor"])
        unit.speed += int(eff.get("speed_delta", 0))
        unit.cs += int(eff.get("cs_delta", 0))
        unit.heat_limit += int(eff.get("heat_limit_delta", 0))
        unit.platforms += int(eff.get("platform_slots_delta", 0))
        hp_bump = int(eff.get("hull_points_delta", 0))
        unit.hp_max += hp_bump
        unit.hp += hp_bump
        unit.reactive_armor_left += int(eff.get("ignore_first_damage", 0))
        if eff.get("ignores_terrain_on_move"):
            unit.ignores_terrain_on_move = True
        if "heat_check_table" in eff:
            unit.heat_check_table = str(eff["heat_check_table"])
