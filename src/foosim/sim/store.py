"""SQLite results store for ``foosim-analyze --db``.

One file accumulates many runs, so a rule tweak can be compared against a baseline
with plain SQL (``WHERE run_id = ...``). Tables:

  runs          one row per invocation: args, ruleset hash, git commit, bots, setup
  games         one row per game (the CSV columns)
  units         one row per mech per game: build + results  (see gamestats.UnitRow)
  unit_weapons  one row per weapon slot per mech per game   (see gamestats.WeaponRow)
  unit_upgrades one row per upgrade per mech per game

Everything joins on ``(run_id, seed)`` (+ ``unit_id``). ``foosim-analyze schema`` prints
the DDL with a one-line meaning per column; both are generated from the dataclasses
here, so the documentation cannot drift from the tables.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field, fields
from pathlib import Path

from foosim.sim.gamestats import UnitRow, WeaponRow

__all__ = ["RunMeta", "Store", "TABLES", "schema_doc", "schema_sql"]

SCHEMA_VERSION = 1

_GAME_DOCS = {
    "seed": "Game seed (setup and dice both derive from it).",
    "winner": "0 | 1 | -1 (draw).",
    "end_reason": "Why the game ended (annihilation, rounds, ...).",
    "rounds": "Rounds played.",
    "steps": "Engine decisions taken.",
    "survivors_0": "Side 0 mechs still in action at the end.",
    "survivors_1": "Side 1 mechs still in action at the end.",
    "damage_dealt": "Total hull damage dealt by both sides, friendly damage included.",
    "crits": "Critical hits.",
    "catastrophics": "Confirmed catastrophic crits.",
    "explosions": "Mechs that exploded.",
    "out_of_action": "Mechs taken out of action.",
    "heat_deaths": "Mechs lost to overheating.",
    "loadout_0": "weapon_id*count list across side 0's starting mechs.",
    "loadout_1": "weapon_id*count list across side 1's starting mechs.",
}


@dataclass
class RunMeta:
    command: str = ""
    label: str = ""
    ruleset_hash: str = ""
    setup: str = ""
    setup_opts: dict = field(default_factory=dict)
    bot0: str = ""
    bot1: str = ""
    seed0: int = 0
    games: int = 0
    overrides: list = field(default_factory=list)


_RUN_COLS = [
    ("run_id", "INTEGER PRIMARY KEY", "Run id (autoincrement)."),
    ("created_utc", "TEXT", "ISO timestamp the run was stored."),
    ("label", "TEXT", "Free-text label from --label."),
    ("command", "TEXT", "The foosim-analyze command line."),
    ("git_commit", "TEXT", "Repo commit the run used ('-dirty' if modified)."),
    ("ruleset_hash", "TEXT", "Hash of the rules in force (includes --override)."),
    ("setup", "TEXT", "urban | scatter | skirmish."),
    ("setup_opts", "TEXT", "JSON: pinned squad/terrain seeds."),
    ("bot0", "TEXT", "Policy for side 0."),
    ("bot1", "TEXT", "Policy for side 1."),
    ("seed0", "INTEGER", "First game seed."),
    ("games", "INTEGER", "Number of games."),
    ("overrides", "TEXT", "JSON list of rules overrides."),
    ("schema_version", "INTEGER", "Store schema version."),
]


def _sqltype(f) -> str:
    t = str(f.type)
    return "REAL" if "float" in t else "INTEGER" if "int" in t else "TEXT"


def _dc_cols(cls, docs=None) -> list[tuple[str, str, str]]:
    return [(f.name, _sqltype(f), (docs or {}).get(f.name) or f.metadata.get("doc", ""))
            for f in fields(cls)]


def _tables() -> dict[str, list[tuple[str, str, str]]]:
    from foosim.sim.analyze import GameRow

    key = [("run_id", "INTEGER", "Run id (runs.run_id).")]
    return {
        "runs": _RUN_COLS,
        "games": key + _dc_cols(GameRow, _GAME_DOCS),
        "units": key + _dc_cols(UnitRow),
        "unit_weapons": key + _dc_cols(WeaponRow),
        "unit_upgrades": key + [
            ("seed", "INTEGER", "Game seed."), ("unit_id", "TEXT", "Owning unit id."),
            ("upgrade_id", "TEXT", "Upgrade id."),
        ],
    }


TABLES = _tables

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_games ON games(run_id, seed)",
    "CREATE INDEX IF NOT EXISTS ix_units ON units(run_id, seed, unit_id)",
    "CREATE INDEX IF NOT EXISTS ix_weapons ON unit_weapons(run_id, weapon_id)",
    "CREATE INDEX IF NOT EXISTS ix_upgrades ON unit_upgrades(run_id, upgrade_id)",
]


def schema_sql() -> str:
    out = []
    for name, cols in _tables().items():
        body = ",\n".join(f"  {c} {t}" for c, t, _ in cols)
        out.append(f"CREATE TABLE IF NOT EXISTS {name} (\n{body}\n);")
    return "\n\n".join(out + [i + ";" for i in _INDEXES]) + "\n"


def schema_doc() -> dict[str, list[dict]]:
    """``{table: [{column, type, doc}]}`` - the machine-readable schema."""
    return {n: [{"column": c, "type": t, "doc": d} for c, t, d in cols]
            for n, cols in _tables().items()}


def _git_commit() -> str:
    try:
        root = Path(__file__).resolve().parents[3]
        rev = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return (rev + "-dirty") if rev and dirty else rev
    except Exception:  # noqa: BLE001 - provenance is best-effort
        return ""


class Store:
    """Append-only results database. Single writer (the parent process)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(schema_sql())

    def close(self) -> None:
        self.db.close()

    def add_run(self, meta: RunMeta, results) -> int:
        """Store a run and all its games; returns the new ``run_id``. ``results`` are
        ``analyze.GameResult`` objects (game row + unit rows + weapon rows)."""
        db = self.db
        with db:
            cur = db.execute(
                "INSERT INTO runs (created_utc, label, command, git_commit, ruleset_hash, setup,"
                " setup_opts, bot0, bot1, seed0, games, overrides, schema_version)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), meta.label, meta.command,
                 _git_commit(), meta.ruleset_hash, meta.setup, json.dumps(meta.setup_opts),
                 meta.bot0, meta.bot1, meta.seed0, meta.games, json.dumps(meta.overrides),
                 SCHEMA_VERSION),
            )
            run_id = int(cur.lastrowid)
            for table, rows in (
                ("games", [r.game for r in results]),
                ("units", [u for r in results for u in r.units]),
                ("unit_weapons", [w for r in results for w in r.weapons]),
            ):
                if not rows:
                    continue
                names = [f.name for f in fields(rows[0])]
                db.executemany(
                    f"INSERT INTO {table} (run_id, {', '.join(names)}) "
                    f"VALUES (?, {', '.join('?' * len(names))})",
                    [(run_id, *(getattr(r, n) for n in names)) for r in rows],
                )
            db.executemany(
                "INSERT INTO unit_upgrades (run_id, seed, unit_id, upgrade_id) VALUES (?,?,?,?)",
                [(run_id, u.seed, u.unit_id, up)
                 for r in results for u in r.units for up in json.loads(u.upgrades)],
            )
        return run_id
