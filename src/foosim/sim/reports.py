"""Canned reports over a ``foosim-analyze --db`` SQLite file.

  foosim-analyze report weapons --db results.sqlite
  foosim-analyze report frames  --db results.sqlite --run 3 --json

Each report returns plain dicts (``--json``) and a text table. All damage figures are
*enemy* damage; friendly fire (e.g. Rail Weapon lane hits) is excluded - see
``sim.gamestats``. Intervals are normal-approximation 95% CIs over mech-games, which
treats mechs in a game as independent; teammates and opponents are not, so read small
differences with care (use a controlled experiment - squad seeds - to isolate).
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict

from foosim.engine.rules import Ruleset

__all__ = ["REPORT_FUNCS", "format_text", "latest_run"]

_TOTAL = "damage_weapon + damage_explosion + damage_self_destruct + damage_other"


def latest_run(db: sqlite3.Connection) -> int:
    row = db.execute("SELECT MAX(run_id) FROM runs").fetchone()
    if row is None or row[0] is None:
        raise SystemExit("error: the database has no runs; create one with `run --db`")
    return int(row[0])


def _mean_ci(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    m = sum(xs) / n
    if n < 2:
        return m, 0.0
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return m, 1.96 * math.sqrt(var / n)


def _marks(runs: list[int]) -> str:
    return ",".join(str(int(r)) for r in runs)


def report_weapons(db, rules: Ruleset, runs: list[int]) -> dict:
    rid = _marks(runs)
    n_mechs = db.execute(f"SELECT COUNT(*) FROM units WHERE run_id IN ({rid})").fetchone()[0]
    per_mech = defaultdict(list)  # weapon_id -> [(attacks, hits, damage, friendly)]
    kinds = {}
    for wid, kind, att, hit, dmg, fr in db.execute(
        f"SELECT weapon_id, kind, SUM(attacks), SUM(hits), SUM(damage), SUM(friendly_damage) "
        f"FROM unit_weapons WHERE run_id IN ({rid}) "
        f"GROUP BY weapon_id, run_id, seed, unit_id"
    ):
        per_mech[wid].append((att, hit, dmg, fr))
        kinds[wid] = kind
    real, synth = [], []
    for wid, rows in per_mech.items():
        dmgs = [r[2] for r in rows]
        mean, ci = _mean_ci(dmgs)
        att, hit = sum(r[0] for r in rows), sum(r[1] for r in rows)
        if kinds[wid] == "synthetic":
            synth.append({
                "weapon": wid, "mechs_with_event": len(rows), "damage": sum(dmgs),
                "friendly_damage_excluded": sum(r[3] for r in rows),
                "damage_per_mech_game": round(sum(dmgs) / max(1, n_mechs), 3),
            })
            continue
        cost = int(rules.weapon(wid).get("cost", 0))
        real.append({
            "weapon": wid, "kind": kinds[wid], "mechs": len(rows), "attacks": att,
            "hit_rate": round(hit / att, 3) if att else 0.0,
            "damage_per_mech_game": round(mean, 3), "ci95": round(ci, 3),
            "damage_per_attack": round(sum(dmgs) / att, 3) if att else 0.0,
            "cost": cost,
            "damage_per_10k": round(mean / (cost / 10000), 3) if cost else None,
            "friendly_damage_excluded": sum(r[3] for r in rows),
        })
    real.sort(key=lambda r: -r["damage_per_mech_game"])
    synth.sort(key=lambda r: -r["damage"])
    return {"title": "Weapons (enemy damage per mech-game carrying the weapon)",
            "rows": real, "synthetic": synth, "mech_games": n_mechs}


def report_frames(db, rules: Ruleset, runs: list[int]) -> dict:
    rid = _marks(runs)
    groups = defaultdict(list)
    for frame, dmg, surv, cost in db.execute(
        f"SELECT frame, {_TOTAL}, survived, cost FROM units WHERE run_id IN ({rid})"
    ):
        groups[frame].append((dmg, surv, cost))
    rows = []
    for frame, g in sorted(groups.items()):
        mean, ci = _mean_ci([x[0] for x in g])
        cost = sum(x[2] for x in g) / len(g)
        rows.append({
            "frame": frame, "mechs": len(g), "damage_per_mech_game": round(mean, 3),
            "ci95": round(ci, 3), "survival": round(sum(x[1] for x in g) / len(g), 3),
            "mean_cost": round(cost), "damage_per_10k": round(mean / (cost / 10000), 3),
        })
    return {"title": "Frames (enemy damage per mech-game)", "rows": rows}


def report_upgrades(db, rules: Ruleset, runs: list[int]) -> dict:
    rid = _marks(runs)
    all_units = {
        (r, s, u): (dmg, surv)
        for r, s, u, dmg, surv in db.execute(
            f"SELECT run_id, seed, unit_id, {_TOTAL}, survived FROM units "
            f"WHERE run_id IN ({rid})")
    }
    have = defaultdict(set)
    for r, s, u, up in db.execute(
        f"SELECT run_id, seed, unit_id, upgrade_id FROM unit_upgrades WHERE run_id IN ({rid})"
    ):
        have[up].add((r, s, u))
    rows = []
    for up, keys in have.items():
        w = [all_units[k] for k in keys if k in all_units]
        wo = [v for k, v in all_units.items() if k not in keys]
        mw, ciw = _mean_ci([x[0] for x in w])
        mo, _ = _mean_ci([x[0] for x in wo])
        rows.append({
            "upgrade": up, "mechs_with": len(w), "damage_with": round(mw, 3),
            "ci95_with": round(ciw, 3), "damage_without": round(mo, 3),
            "diff": round(mw - mo, 3),
            "survival_with": round(sum(x[1] for x in w) / len(w), 3) if w else 0.0,
            "survival_without": round(sum(x[1] for x in wo) / len(wo), 3) if wo else 0.0,
            "cost": int(rules.upgrade(up).get("cost", 0)),
        })
    rows.sort(key=lambda r: -r["diff"])
    return {"title": "Upgrades (mechs with vs without; confounded by frame)", "rows": rows}


REPORT_FUNCS = {"weapons": report_weapons, "frames": report_frames, "upgrades": report_upgrades}


def _table(rows: list[dict]) -> list[str]:
    if not rows:
        return ["  (no rows)"]
    cols = list(rows[0])
    cells = [[("" if r[c] is None else str(r[c])) for c in cols] for r in rows]
    w = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(cols)]
    line = lambda vals: "  " + "  ".join(v.rjust(w[i]) for i, v in enumerate(vals))  # noqa: E731
    return [line(cols), *(line(r) for r in cells)]


def format_text(result: dict, runs: list[int]) -> str:
    out = [result["title"] + f"   [run(s) {_marks(runs)}]", ""]
    out += _table(result["rows"])
    if result.get("synthetic"):
        out += ["", "Synthetic weapons (damage not tied to a weapon slot):"]
        out += _table(result["synthetic"])
    return "\n".join(out)
