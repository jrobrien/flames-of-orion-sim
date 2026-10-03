"""What ``foosim-analyze`` can run, described once for humans and machines.

Everything the help system prints - ``list``, ``describe``, ``manifest`` - comes from
here (plus the dataclass column docs in ``gamestats`` / ``store`` and the rules file),
so help cannot drift from behaviour: ``tests/test_catalog.py`` fails if a bot or setup
in ``analyze`` has no entry here, or an entry has no description.
"""

from __future__ import annotations

from foosim.engine.effects import (
    ammo_supported,
    perk_supported,
    upgrade_supported,
    weapon_supported,
)
from foosim.engine.rules import Ruleset

__all__ = ["BOTS", "REPORTS", "SETUPS", "gear", "metrics"]

BOTS: dict[str, dict] = {
    "random": {
        "summary": "Picks uniformly among legal actions; the regression baseline.",
        "description": (
            "Each activation: picks a random unit, then a uniformly random legal action; "
            "after the first action it ends the activation 1/3 of the time. When the mech "
            "has heat headroom it leans (75%) toward bolstered variants, mimicking table "
            "play. Never plans, so it wastes shots and rarely retreats - useful as a floor "
            "and to check a result is not an artefact of the smarter bot. It can pick Self "
            "Destruct at random, unlike greedy."
        ),
        "params": {"bolster_bias": "0..1 chance to prefer bolstered actions (default 0.75)"},
        "class": "foosim.ai.policy.RandomPolicy",
    },
    "greedy": {
        "summary": "Scores every legal action and plays the best; the analysis default.",
        "description": (
            "Front-line units activate first. Each action is scored: attacks by expected "
            "damage (hit chance x damage through armor, plus catastrophic and likely-kill "
            "bonuses; firing all weapons is favoured), moves by closing distance (retreat "
            "when hurt), disengage when hurt, purge heat when near the limit, all minus a "
            "heat penalty. Self Destruct triggers only at HP<=2 with 2+ enemies and no "
            "friendlies in the blast. Ties within 0.05 are broken randomly. Beats random "
            "handily. NOTE: because it scores by expected damage, results favour "
            "weapons that look good to this heuristic; cross-check with random."
        ),
        "params": {"aggression": "multiplier on attack value (default 1.0)"},
        "class": "foosim.ai.policy.GreedyPolicy",
    },
}

SETUPS: dict[str, dict] = {
    "urban": {
        "summary": "4v4 random quick-play squads on a 30x30 city map (default).",
        "description": (
            "Each side fields a quick-play squad: a Heavy leader (with one supported "
            "perk), two Mediums and a Light, all rolled on the Black Market tables using "
            "only gear the simulator implements. Dense blocking and cover buildings; "
            "squads deploy in opposite 3-row zones. Squads, map and dice all vary with "
            "the game seed unless pinned."
        ),
        "options": ["--squad-seed", "--squad-seed-0", "--squad-seed-1", "--terrain-seed",
                    "--mirror"],
        "best_for": "builds, weapons and frames in the usual game format",
    },
    "scatter": {
        "summary": "Same squads as urban on a sparse map (8 blockers, 12 cover).",
        "description": (
            "As urban but open ground: favours ranged and long-range weapons, fewer "
            "line-of-sight blocks. Use to see how much a result depends on the map."
        ),
        "options": ["--squad-seed", "--squad-seed-0", "--squad-seed-1", "--terrain-seed",
                    "--mirror"],
        "best_for": "checking map sensitivity",
    },
    "skirmish": {
        "summary": "Fixed 2v2 on a small map; fast, no random squads.",
        "description": (
            "Two fixed mechs per side on a small board. Not for build analysis (the "
            "squads are fixed) but fast for rule A/B tests and regression."
        ),
        "options": [],
        "best_for": "quick rule A/B comparisons",
    },
}

REPORTS: dict[str, dict] = {
    "weapons": {
        "summary": "Per-weapon damage, accuracy, cost-efficiency (+ synthetic weapons).",
        "description": (
            "For each weapon: mechs carrying it, attacks, hit rate, mean enemy damage per "
            "mech-game with a 95% interval, damage per attack, price and damage per "
            "10,000$. Synthetic weapons (explosion, self_destruct, ram, terrain_collapse) "
            "are listed separately. Friendly damage is excluded."
        ),
    },
    "frames": {
        "summary": "Light vs medium vs heavy: damage, survival, cost-efficiency.",
        "description": "Per frame: mechs, mean damage dealt (all enemy-damage sources), "
                       "survival rate, mean cost and damage per 10,000$.",
    },
    "upgrades": {
        "summary": "Mechs with each upgrade vs mechs without.",
        "description": "Per upgrade: mean damage dealt and survival for mechs carrying it "
                       "vs the rest. Confounded by frame and teammates - see the guide's "
                       "controlled-experiment section before trusting small differences.",
    },
}


def gear(rules: Ruleset) -> list[dict]:
    """Every weapon / ammo / upgrade / perk with price and whether the sim implements it."""
    out: list[dict] = []
    raw = rules.raw
    for kind, key, ok in (("ranged_weapon", "ranged_weapons", weapon_supported),
                          ("melee_weapon", "melee_weapons", weapon_supported),
                          ("ammo", "ammo", ammo_supported),
                          ("upgrade", "upgrades", upgrade_supported),
                          ("perk", "perks", perk_supported)):
        for g in raw.get(key, []):
            out.append({"type": kind, "id": g["id"], "name": g["name"],
                        "cost": g.get("cost"), "simulated": bool(ok(g)),
                        "damage": g.get("damage")})
    return out


def metrics() -> dict[str, list[dict]]:
    """Column documentation for the per-mech and per-weapon data."""
    from foosim.sim.store import schema_doc

    d = schema_doc()
    return {k: d[k] for k in ("units", "unit_weapons", "games")}
