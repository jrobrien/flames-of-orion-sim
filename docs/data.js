window.FOO_DATA = {
 "mechCost": 50000,
 "frames": {
  "light": {
   "speed": 7,
   "combat_skill": 4,
   "armor": 6,
   "hull_points": 4,
   "heat_limit": 12,
   "platform_slots": 3
  },
  "medium": {
   "speed": 6,
   "combat_skill": 4,
   "armor": 6,
   "hull_points": 6,
   "heat_limit": 10,
   "platform_slots": 4
  },
  "heavy": {
   "speed": 5,
   "combat_skill": 4,
   "armor": 5,
   "hull_points": 7,
   "heat_limit": 9,
   "platform_slots": 5
  }
 },
 "ranged": [
  {
   "id": "flame_thrower",
   "name": "Flame Thrower",
   "damage": "1",
   "slots": 1,
   "cost": 10000,
   "text": "Range 10\"; target +1d2 heat on hit; no ammo",
   "noAmmo": true
  },
  {
   "id": "light_weapon",
   "name": "Light Weapon",
   "damage": "1",
   "slots": 1,
   "cost": 10000,
   "text": "",
   "noAmmo": false
  },
  {
   "id": "medium_weapon",
   "name": "Medium Weapon",
   "damage": "2",
   "slots": 1,
   "cost": 15000,
   "text": "",
   "noAmmo": false
  },
  {
   "id": "heavy_weapon",
   "name": "Heavy Weapon",
   "damage": "4",
   "slots": 2,
   "cost": 25000,
   "text": "Half speed if fired (2 PF)",
   "noAmmo": false
  },
  {
   "id": "rail_weapon",
   "name": "Rail Weapon",
   "damage": "d3",
   "slots": 1,
   "cost": 45000,
   "text": "Line attack; hits friendlies; +1 heat to self",
   "noAmmo": false
  },
  {
   "id": "ai_missile_system",
   "name": "A.I. Missile System",
   "damage": "1",
   "slots": 1,
   "cost": 15000,
   "text": "Range 20\"; ignores LOS, cover, long-range penalty",
   "noAmmo": false
  },
  {
   "id": "long_range_systems",
   "name": "Long Range Systems",
   "damage": "2",
   "slots": 1,
   "cost": 25000,
   "text": "Armor penetration; no long-range penalty",
   "noAmmo": false
  },
  {
   "id": "large_missile_battery",
   "name": "Large Missile Battery",
   "damage": "d2",
   "slots": 1,
   "cost": 30000,
   "text": "Splash 2\"",
   "noAmmo": false
  }
 ],
 "melee": [
  {
   "id": "basic_combat_attachment",
   "name": "Basic Combat Attachment",
   "damage": "1",
   "slots": 1,
   "cost": 5000,
   "text": "",
   "noAmmo": false
  },
  {
   "id": "close_combat_weapon",
   "name": "Close Combat Weapon",
   "damage": "2",
   "slots": 1,
   "cost": 10000,
   "text": "",
   "noAmmo": false
  },
  {
   "id": "cable_whip",
   "name": "Cable Whip",
   "damage": "2",
   "slots": 1,
   "cost": 15000,
   "text": "Reach 3\"",
   "noAmmo": false
  },
  {
   "id": "lance",
   "name": "Lance",
   "damage": "1",
   "slots": 1,
   "cost": 20000,
   "text": "+2 dmg and AP if moved",
   "noAmmo": false
  },
  {
   "id": "power_weapon",
   "name": "Power Weapon",
   "damage": "2",
   "slots": 1,
   "cost": 15000,
   "text": "Armor penetration; on a 1 loses AP",
   "noAmmo": false
  },
  {
   "id": "electric_field",
   "name": "Electric Field",
   "damage": "1",
   "slots": 1,
   "cost": 10000,
   "text": "Hits all within 2\"; push 1\"",
   "noAmmo": false
  },
  {
   "id": "piston_gauntlet",
   "name": "Piston Gauntlet",
   "damage": "2",
   "slots": 1,
   "cost": 10000,
   "text": "Push target 1\" on hit",
   "noAmmo": false
  },
  {
   "id": "energy_sword",
   "name": "Energy Sword",
   "damage": "2",
   "slots": 1,
   "cost": 15000,
   "text": "Crit on 5+; on a 1 becomes 1 dmg",
   "noAmmo": false
  }
 ],
 "ammo": [
  {
   "id": "flechette_rounds",
   "name": "Flechette Rounds",
   "cost": 5000,
   "text": "armor penetration"
  },
  {
   "id": "hellfire_rounds",
   "name": "Hellfire Rounds",
   "cost": 10000,
   "text": "+1 dmg"
  },
  {
   "id": "emf_rounds",
   "name": "EMF Rounds",
   "cost": 10000,
   "text": "target -2 S until its next activation"
  },
  {
   "id": "concussive_rounds",
   "name": "Concussive Rounds",
   "cost": 5000,
   "text": "push 2\"; 1 collision dmg"
  },
  {
   "id": "rapid_fire_rounds",
   "name": "Rapid Fire Rounds",
   "cost": 20000,
   "text": "extra attack on a hit roll of 6"
  },
  {
   "id": "tracer_rounds",
   "name": "Tracer Rounds",
   "cost": 5000,
   "text": "both positions compromised"
  }
 ],
 "upgrades": [
  {
   "id": "armor_mk1",
   "name": "Armor Mk I",
   "cost": 10000,
   "stackable": false,
   "effect": {
    "set_armor": 5
   },
   "text": "AR 5+"
  },
  {
   "id": "armor_mk2",
   "name": "Armor Mk II",
   "cost": 25000,
   "stackable": false,
   "effect": {
    "set_armor": 4
   },
   "text": "AR 4+"
  },
  {
   "id": "reactive_armor",
   "name": "Reactive Armor",
   "cost": 50000,
   "stackable": false,
   "effect": {
    "ignore_first_damage": 1
   },
   "text": "Ignore the first damage taken"
  },
  {
   "id": "vtol",
   "name": "VTOL",
   "cost": 25000,
   "stackable": false,
   "effect": {
    "ignores_terrain_on_move": true
   },
   "text": "Ignores terrain when moving"
  },
  {
   "id": "thrusters",
   "name": "Thrusters",
   "cost": 10000,
   "stackable": true,
   "effect": {
    "speed_delta": 1
   },
   "text": "+1 S"
  },
  {
   "id": "heat_sink",
   "name": "Heat Sink",
   "cost": 10000,
   "stackable": false,
   "effect": {
    "heat_check_table": "check_heat_sink"
   },
   "text": "Uses the Heat Sink heat-check table"
  },
  {
   "id": "sensor_array",
   "name": "Sensor Array",
   "cost": 25000,
   "stackable": false,
   "effect": {
    "crit_bonus_damage": 1
   },
   "text": "Crits do +1 damage"
  },
  {
   "id": "heavy_plating",
   "name": "Heavy Plating",
   "cost": 20000,
   "stackable": true,
   "effect": {
    "hull_points_delta": 1
   },
   "text": "+1 HP"
  },
  {
   "id": "core_stabilizers",
   "name": "Core Stabilizers",
   "cost": 10000,
   "stackable": true,
   "effect": {
    "heat_limit_delta": 2
   },
   "text": "+2 HL"
  },
  {
   "id": "extra_platforms",
   "name": "Extra Platforms",
   "cost": 15000,
   "stackable": true,
   "effect": {
    "platform_slots_delta": 1,
    "free_slot": true
   },
   "text": "+1 PF (takes no slot)"
  },
  {
   "id": "self_destruct",
   "name": "Self Destruct",
   "cost": 10000,
   "stackable": false,
   "effect": {},
   "text": "Action: self-destruct at heat 7+"
  },
  {
   "id": "camouflage",
   "name": "Camouflage",
   "cost": 30000,
   "stackable": false,
   "effect": {
    "enemy_ranged_cs_penalty": 1
   },
   "text": "Action: active camo; enemy ranged CS penalty"
  },
  {
   "id": "nuclear_core",
   "name": "Nuclear Core",
   "cost": 10000,
   "stackable": false,
   "effect": {
    "explode_as_heat": 10
   },
   "text": "Explodes as 10 heat"
  },
  {
   "id": "targeting_system",
   "name": "Targeting System",
   "cost": 45000,
   "stackable": false,
   "effect": {
    "cs_delta": -1
   },
   "text": "+1 CS"
  },
  {
   "id": "up_link",
   "name": "Up-Link",
   "cost": 15000,
   "stackable": false,
   "effect": {},
   "text": "Action: Up-Link (position compromised)"
  },
  {
   "id": "long_range_targeting",
   "name": "Long Range Targeting",
   "cost": 15000,
   "stackable": false,
   "effect": {
    "ignores_long_range_penalty": true
   },
   "text": "Ignores long-range penalty"
  },
  {
   "id": "defense_array",
   "name": "Defense Array",
   "cost": 10000,
   "stackable": false,
   "effect": {},
   "text": "Repel within 1\" on 4+"
  },
  {
   "id": "thermal_imaging",
   "name": "Thermal Imaging",
   "cost": 20000,
   "stackable": false,
   "effect": {
    "cs_delta_vs_hot_target": -1,
    "hot_threshold": 5
   },
   "text": "+1 CS vs targets at heat 5+"
  },
  {
   "id": "counter_missiles",
   "name": "Counter Missiles",
   "cost": 10000,
   "stackable": false,
   "effect": {
    "negate_ranged_crit_bonus_damage": true
   },
   "text": "Negates ranged crit bonus damage"
  },
  {
   "id": "virus_program",
   "name": "Virus Program",
   "cost": 20000,
   "stackable": false,
   "effect": {},
   "text": "Action: infect (once per game)"
  }
 ],
 "perks": [
  {
   "id": "calm_and_collected",
   "name": "Calm & Collected",
   "text": "+1 to HEAT Check rolls"
  },
  {
   "id": "demolition_expert",
   "name": "Demolition Expert",
   "text": "Buildings damaged by this model's weapons are destroyed"
  },
  {
   "id": "running_hot",
   "name": "Running Hot",
   "text": "Double the radius of this model's explosion"
  },
  {
   "id": "close_combat_expert",
   "name": "Close Combat Expert",
   "text": "+1 CS for melee attacks",
   "requires": "melee",
   "effect": {
    "cs_delta_melee": 1
   }
  },
  {
   "id": "ranged_expert",
   "name": "Ranged Expert",
   "text": "+1 CS for ranged attacks",
   "requires": "ranged",
   "effect": {
    "cs_delta_ranged": 1
   }
  },
  {
   "id": "heat_expert",
   "name": "HEAT Expert",
   "text": "+1 HEAT Limit",
   "effect": {
    "heat_limit_delta": 1
   }
  },
  {
   "id": "hydraulics_overhaul",
   "name": "Hydraulics Overhaul",
   "text": "+1 Speed",
   "effect": {
    "speed_delta": 1
   }
  }
 ],
 "callSignA": [
  [
   "A color",
   "Iron",
   "Fury",
   "Death",
   "Steel",
   "Rust"
  ],
  [
   "Heavy",
   "Divine",
   "Alpha",
   "Infernal",
   "Vengeful",
   "Eternal"
  ],
  [
   "Dark",
   "Hell",
   "Phantom",
   "Heavens",
   "An animal",
   "Gloom"
  ],
  [
   "Hard",
   "Wraith",
   "War",
   "Cold",
   "Havoc",
   "Dread"
  ],
  [
   "Sin",
   "Void",
   "Night",
   "Siege",
   "Relentless",
   "Acid"
  ],
  [
   "Pain",
   "Sacred",
   "Frenzied",
   "Chrono",
   "Wayward",
   "Grim"
  ]
 ],
 "callSignB": [
  [
   "A number",
   "Blade",
   "Talon",
   "Demon",
   "Reaver",
   "Battery"
  ],
  [
   "Frame",
   "Armor",
   "Wraith",
   "Steel",
   "Sentinel",
   "Unit"
  ],
  [
   "Herald",
   "Tank",
   "Machine",
   "Angel",
   "Wyvern",
   "Walker"
  ],
  [
   "Titan",
   "Shadow",
   "Gear",
   "Core",
   "Engine",
   "Gun"
  ],
  [
   "Hound",
   "Scout",
   "Master",
   "Devil",
   "Stalker",
   "Ghost"
  ],
  [
   "Flame",
   "Saber",
   "Strider",
   "Dragon",
   "Spirit",
   "Javelin"
  ]
 ]
};
