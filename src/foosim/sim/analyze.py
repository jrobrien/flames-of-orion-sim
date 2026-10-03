"""Bulk auto-battle analysis - the "run N games, tweak a rule, diff" workflow.

  foosim-analyze --games 500 --matchup greedy-vs-greedy
  foosim-analyze --games 500 --override heat.second_action=2 --out variant.csv \\
                 --baseline base.csv

Games run across all CPUs by default (``-j N`` to limit, ``-j 1`` for in-process).
Stdlib only, so it runs in CI. Per-game rows -> CSV; a summary dict -> stdout;
``diff(a, b)`` for baseline vs variant.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from foosim.ai.policy import GreedyPolicy, RandomPolicy
from foosim.engine.rules import Ruleset
from foosim.engine.rules import load as load_rules
from foosim.sim.autobattle import run_game
from foosim.sim.gamestats import UnitRow, WeaponRow, extract
from foosim.sim.generate import random_setup
from foosim.sim.setups import skirmish_2v2

__all__ = [
    "GameResult",
    "GameRow",
    "diff",
    "parse_override",
    "read_csv",
    "run_games",
    "run_many",
    "run_one",
    "run_one_full",
    "run_parallel",
    "summarize",
    "write_csv",
]

_POLICIES = {"greedy": GreedyPolicy, "random": RandomPolicy}
_SETUPS = {
    "urban": lambda r, s, **o: random_setup(r, seed=s, **o),                       # 4v4 city
    "scatter": lambda r, s, **o: random_setup(r, seed=s, terrain="scatter", **o),  # 4v4 sparse
    "skirmish": lambda r, s, **o: skirmish_2v2(r, seed=s, **o),                    # fixed 2v2
}


@dataclass
class GameRow:
    seed: int
    winner: int  # 0 | 1 | -1 (draw)
    end_reason: str
    rounds: int
    steps: int
    survivors_0: int
    survivors_1: int
    damage_dealt: int
    crits: int
    catastrophics: int
    explosions: int
    out_of_action: int
    heat_deaths: int
    loadout_0: str = ""  # "<weapon_id>*<count>,..." across side 0's starting mechs
    loadout_1: str = ""


_STR_FIELDS = frozenset({"end_reason", "loadout_0", "loadout_1"})


def loadout_string(state, side: int) -> str:
    from collections import Counter

    c: Counter[str] = Counter()
    for u in state.units.values():
        if u.side == side:
            c.update(w.weapon_id for w in u.weapons)
    return ",".join(f"{k}*{v}" for k, v in sorted(c.items()))


@dataclass
class GameResult:
    """One finished game: the per-game row plus per-mech and per-weapon detail."""

    game: GameRow
    units: list[UnitRow]
    weapons: list[WeaponRow]


def run_one(setup, policies, rules: Ruleset, seed: int) -> GameRow:
    return run_one_full(setup, policies, rules, seed).game


def run_one_full(setup, policies, rules: Ruleset, seed: int) -> GameResult:
    initial = setup.copy()
    loadout_0 = loadout_string(setup, 0)
    loadout_1 = loadout_string(setup, 1)
    final, events, steps = run_game(setup, policies, rules)
    dmg = crits = cats = booms = ooa = heat_deaths = 0
    for e in events:
        k = e.kind
        if k == "damage":
            dmg += int(e.data.get("amount", 0))
        elif k == "critical":
            crits += 1
        elif k == "catastrophic":
            cats += 1
        elif k == "explosion":
            booms += 1
        elif k == "out_of_action":
            ooa += 1
            if e.data.get("cause") == "overheat":
                heat_deaths += 1
    units, weapons = extract(initial, final, events, rules, seed)
    game = GameRow(
        seed=seed,
        winner=final.winner if final.winner is not None else -1,
        end_reason=final.end_reason or "?",
        rounds=min(final.round, rules.game["rounds"]),
        steps=steps,
        survivors_0=len(final.live_units(0)),
        survivors_1=len(final.live_units(1)),
        damage_dealt=dmg,
        crits=crits,
        catastrophics=cats,
        explosions=booms,
        out_of_action=ooa,
        heat_deaths=heat_deaths,
        loadout_0=loadout_0,
        loadout_1=loadout_1,
    )
    return GameResult(game, units, weapons)


def run_many(make_setup, make_policies, rules: Ruleset, *, n: int, seed0: int = 0) -> list[GameRow]:
    """``make_setup(seed) -> GameState``; ``make_policies(seed) -> {0: Policy, 1: Policy}``."""
    return [
        run_one(make_setup(s), make_policies(s), rules, s)
        for s in range(seed0, seed0 + n)
    ]


def _factories(rules: Ruleset, setup: str, p0: str, p1: str, opts: dict | None = None):
    """Per-seed setup / policy factories for named setups and policies. ``opts`` are
    extra setup keyword args (``squad_seed_0`` / ``squad_seed_1`` / ``terrain_seed``)."""
    setup_fn, P0, P1 = _SETUPS[setup], _POLICIES[p0], _POLICIES[p1]
    opts = dict(opts or {})
    return (
        lambda s: setup_fn(rules, s, **opts),
        lambda s: {0: P0(rules, s * 2 + 1), 1: P1(rules, s * 2 + 2)},
    )


# Worker-process state, set once per worker by _init_worker.
_WORKER: tuple | None = None


def _init_worker(rules: Ruleset, setup: str, p0: str, p1: str, opts: dict) -> None:
    global _WORKER
    _WORKER = (rules, *_factories(rules, setup, p0, p1, opts))


def _run_seed(seed: int) -> GameResult:
    assert _WORKER is not None
    rules, make_setup, make_policies = _WORKER
    return run_one_full(make_setup(seed), make_policies(seed), rules, seed)


def run_parallel(*args, **kw) -> list[GameRow]:
    """``run_games`` keeping only the per-game rows."""
    return [r.game for r in run_games(*args, **kw)]


def run_games(
    rules: Ruleset, setup: str, p0: str, p1: str, *, n: int, seed0: int = 0,
    jobs: int | None = None, progress: bool = False, setup_opts: dict | None = None,
) -> list[GameResult]:
    """``run_many`` for named setups/policies across worker processes. Each game depends
    only on its seed, so rows come back in seed order and are identical to a serial
    run. ``jobs`` of ``None`` uses every CPU; ``1`` stays in-process."""
    seeds = range(seed0, seed0 + n)
    jobs = min(jobs or os.cpu_count() or 1, n) or 1
    if jobs <= 1:
        make_setup, make_policies = _factories(rules, setup, p0, p1, setup_opts)
        return [run_one_full(make_setup(sd), make_policies(sd), rules, sd) for sd in seeds]
    rows: list[GameResult] = []
    with ProcessPoolExecutor(
        max_workers=jobs, initializer=_init_worker,
        initargs=(rules, setup, p0, p1, dict(setup_opts or {})),
    ) as pool:
        for row in pool.map(_run_seed, seeds, chunksize=max(1, min(16, n // (jobs * 4)))):
            rows.append(row)
            if progress:
                print(f"\r  {len(rows)}/{n} games", end="", file=sys.stderr, flush=True)
    if progress:
        print(file=sys.stderr)
    return rows


def summarize(rows: list[GameRow]) -> dict:
    n = len(rows)
    if n == 0:
        return {"games": 0}

    def mean(f) -> float:
        return sum(f(r) for r in rows) / n

    return {
        "games": n,
        "win_rate_0": mean(lambda r: r.winner == 0),
        "win_rate_1": mean(lambda r: r.winner == 1),
        "draw_rate": mean(lambda r: r.winner == -1),
        "decisive_rate": mean(lambda r: r.winner in (0, 1)),
        "annihilation_rate": mean(lambda r: r.end_reason == "annihilation"),
        "mean_rounds": mean(lambda r: r.rounds),
        "mean_steps": mean(lambda r: r.steps),
        "mean_survivors_0": mean(lambda r: r.survivors_0),
        "mean_survivors_1": mean(lambda r: r.survivors_1),
        "mean_damage": mean(lambda r: r.damage_dealt),
        "mean_crits": mean(lambda r: r.crits),
        "mean_catastrophics": mean(lambda r: r.catastrophics),
        "mean_explosions": mean(lambda r: r.explosions),
        "mean_heat_deaths": mean(lambda r: r.heat_deaths),
        "distinct_matchups": len({(r.loadout_0, r.loadout_1) for r in rows}),
    }


def diff(base: dict, variant: dict) -> dict:
    """``variant - base`` for every numeric key they share."""
    return {
        k: variant[k] - base[k]
        for k in base
        if k in variant and isinstance(base[k], (int, float)) and not isinstance(base[k], bool)
    }


def parse_override(s: str) -> tuple[str, object]:
    key, sep, raw = s.partition("=")
    if not sep:
        raise ValueError(f"override must be DOTTED.PATH=VALUE, got {s!r}")
    if raw.lower() in ("true", "false"):
        return key, raw.lower() == "true"
    for cast in (int, float):
        try:
            return key, cast(raw)
        except ValueError:
            pass
    return key, raw


def write_csv(rows: list[GameRow], path: str | Path) -> None:
    cols = [f.name for f in fields(GameRow)]
    with Path(path).open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def read_csv(path: str | Path) -> list[GameRow]:
    ints = {f.name for f in fields(GameRow)} - _STR_FIELDS
    out = []
    with Path(path).open(newline="") as fh:
        for d in csv.DictReader(fh):
            out.append(GameRow(**{k: (int(v) if k in ints else v) for k, v in d.items()}))
    return out


def _fmt(summary: dict) -> str:
    return "\n".join(
        f"  {k:20s} {v:.3f}" if isinstance(v, float) else f"  {k:20s} {v}"
        for k, v in summary.items()
    )


def _run_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="foosim-analyze run",
        description="Run N auto-battles in parallel and summarize (and optionally store) "
                    "the results. Games are numbered by seed: seed..seed+N-1; each game's "
                    "squads, map and dice derive from its seed unless pinned.",
        epilog=_RUN_EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", type=int, default=200,
                    help="number of games to play (default 200); 500+ for stable averages")
    ap.add_argument("--seed", type=int, default=0,
                    help="first game seed; games use seed..seed+N-1 (default 0). Same seed + "
                         "rules + options always reproduces the same games")
    ap.add_argument("--setup", choices=list(_SETUPS), default="urban",
                    help="battlefield + squads: " + ", ".join(_SETUPS)
                         + " (see `foosim-analyze list setups`)")
    ap.add_argument("--matchup", default="greedy-vs-greedy",
                    help="BOT0-vs-BOT1, bots: " + ", ".join(_POLICIES)
                         + " (see `foosim-analyze list bots`)")
    ap.add_argument("--override", action="append", default=[], metavar="PATH=VALUE",
                    help="override a rules.toml value for this run, e.g. heat.second_action=2 "
                         "(repeatable); changes the ruleset hash")
    ap.add_argument("--squad-seed", type=int, metavar="N",
                    help="pin BOTH squads to this seed (same squads every game; same value "
                         "on both sides = mirror match)")
    ap.add_argument("--squad-seed-0", type=int, metavar="N", help="pin side 0's squad only")
    ap.add_argument("--squad-seed-1", type=int, metavar="N", help="pin side 1's squad only")
    ap.add_argument("--terrain-seed", type=int, metavar="N", help="pin the map to this seed")
    ap.add_argument("--mirror", action="store_true",
                    help="side 1 gets a copy of side 0's squad every game (squads still vary "
                         "per game): removes build differences, leaving bot/luck/position")
    ap.add_argument("-j", "--jobs", type=int, default=None, metavar="N",
                    help="worker processes (default: all CPUs; 1 = run in-process)")
    ap.add_argument("--out", metavar="CSV",
                    help="write per-game rows (one line per game, no per-mech detail) here")
    ap.add_argument("--db", metavar="SQLITE",
                    help="append this run (games, per-mech builds + damage, per-weapon "
                         "stats) to a SQLite file; see `foosim-analyze schema`")
    ap.add_argument("--label", default="", help="free-text label stored with the run in --db")
    ap.add_argument("--baseline", metavar="CSV",
                    help="a previous --out CSV; prints this run's summary minus the baseline's")
    return ap


def _cmd_run(argv: list[str]) -> None:
    ap = _run_parser()
    args = ap.parse_args(argv)

    rules = load_rules()
    if args.override:
        rules = rules.with_overrides(dict(parse_override(o) for o in args.override))

    p0_name, _, p1_name = args.matchup.partition("-vs-")
    for bot in (p0_name, p1_name):
        if bot not in _POLICIES:
            ap.error(_unknown("bot", bot, _POLICIES) + "  (matchup form: greedy-vs-random)")
    setup_opts = {
        "squad_seed_0": args.squad_seed if args.squad_seed_0 is None else args.squad_seed_0,
        "squad_seed_1": args.squad_seed if args.squad_seed_1 is None else args.squad_seed_1,
        "terrain_seed": args.terrain_seed,
        "mirror": args.mirror or None,
    }
    setup_opts = {k: v for k, v in setup_opts.items() if v is not None}
    if setup_opts and args.setup == "skirmish":
        ap.error("squad/terrain seeds apply to the urban and scatter setups only")
    results = run_games(
        rules, args.setup, p0_name, p1_name, n=args.games, seed0=args.seed,
        jobs=args.jobs, progress=sys.stderr.isatty(), setup_opts=setup_opts,
    )
    rows = [r.game for r in results]
    summary = summarize(rows)

    print(f"{args.matchup} on {args.setup}  ({args.games} games, ruleset {rules.content_hash})")
    if args.override:
        print("  overrides: " + ", ".join(args.override))
    print(_fmt(summary))

    if args.out:
        write_csv(rows, args.out)
        print(f"  wrote {args.out}")
    if args.db:
        from foosim.sim.store import RunMeta, Store

        store = Store(args.db)
        run_id = store.add_run(
            RunMeta(
                command=" ".join(["foosim-analyze", *(argv if argv is not None else sys.argv[1:])]),
                label=args.label, ruleset_hash=rules.content_hash, setup=args.setup,
                setup_opts=setup_opts, bot0=p0_name, bot1=p1_name, seed0=args.seed,
                games=args.games, overrides=list(args.override),
            ),
            results,
        )
        store.close()
        print(f"  stored run {run_id} in {args.db}")
    if args.baseline:
        base = summarize(read_csv(args.baseline))
        print(f"\nvs baseline {args.baseline}:")
        print(_fmt(diff(base, summary)))


# --------------------------------------------------------------------------
# help system / subcommands
# --------------------------------------------------------------------------

_RUN_EXAMPLES = """\
examples:
  foosim-analyze run --games 500                            # greedy-vs-greedy, urban 4v4
  foosim-analyze run --games 2000 --db results.sqlite       # + per-mech/per-weapon data
  foosim-analyze run --games 500 --matchup greedy-vs-random --setup scatter
  foosim-analyze run --games 500 --override heat.second_action=2 --baseline base.csv
  foosim-analyze run --games 500 --squad-seed-0 7 --db r.sqlite   # same side-0 squad each game
"""

_COMMANDS = {
    "run": "Run games; print a summary; optionally write --out CSV / --db SQLite.",
    "list": "List bots, setups, gear, metrics, reports, tables (add --json).",
    "describe": "Full description of one bot, setup, report, gear item or table.",
    "schema": "SQLite tables and every column's meaning (--sql for DDL, --json).",
    "report": "Canned analyses over a --db file: weapons, frames, upgrades.",
    "manifest": "Machine-readable JSON of all commands, flags, bots, setups, schema, gear.",
}


def _unknown(what: str, got: str, valid) -> str:
    import difflib

    valid = list(valid)
    near = difflib.get_close_matches(got, valid, n=1)
    hint = f" Did you mean '{near[0]}'?" if near else ""
    return f"unknown {what} '{got}'.{hint} Valid: {', '.join(valid)}"


def _overview() -> str:
    from foosim.sim import catalog

    cmds = "\n".join(f"  {k:<9} {v}" for k, v in _COMMANDS.items())
    bots = "\n".join(f"  {k:<9} {v['summary']}" for k, v in catalog.BOTS.items())
    setups = "\n".join(f"  {k:<9} {v['summary']}" for k, v in catalog.SETUPS.items())
    return f"""\
foosim-analyze - bulk Flames of Orion auto-battles: run N games, then analyze.

commands:
{cmds}

bots (who plays each side; --matchup BOT0-vs-BOT1):
{bots}

setups (battlefield and squads; --setup NAME):
{setups}

typical workflows:
  Which weapons / builds deal the most damage?
    foosim-analyze run --games 2000 --db results.sqlite
    foosim-analyze report weapons --db results.sqlite
    foosim-analyze report frames  --db results.sqlite
  Did a rules change help?  (A/B on the same seeds)
    foosim-analyze run --games 500 --out base.csv
    foosim-analyze run --games 500 --override heat.second_action=2 --baseline base.csv
  Isolate a variable (hold side 0's squad fixed, vary everything else):
    foosim-analyze run --games 500 --squad-seed-0 7 --db results.sqlite

Run `foosim-analyze <command> --help` for flags, `list`/`describe` for what things are,
`manifest` for everything as JSON. Guide: docs/analysis-guide.md
"""


def _json_out(obj) -> None:
    import json

    print(json.dumps(obj, indent=2, default=str))


def _cmd_list(argv: list[str]) -> None:
    from foosim.sim import catalog, store

    kinds = ("bots", "setups", "gear", "metrics", "reports", "tables")
    ap = argparse.ArgumentParser(prog="foosim-analyze list", description=_COMMANDS["list"])
    ap.add_argument("what", nargs="?", choices=kinds, help="one of: " + ", ".join(kinds))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.what is None:
        ap.error("what to list? one of: " + ", ".join(kinds))
    rules = load_rules()
    data = {
        "bots": {k: v["summary"] for k, v in catalog.BOTS.items()},
        "setups": {k: v["summary"] for k, v in catalog.SETUPS.items()},
        "reports": {k: v["summary"] for k, v in catalog.REPORTS.items()},
        "gear": catalog.gear(rules),
        "metrics": catalog.metrics(),
        "tables": {t: len(c) for t, c in store.schema_doc().items()},
    }[args.what]
    if args.json:
        _json_out(data)
    elif args.what == "gear":
        print(f"{'type':<14}{'id':<26}{'cost':>8}  simulated  name")
        for g in data:
            print(f"{g['type']:<14}{g['id']:<26}{g['cost'] or '':>8}  "
                  f"{'yes' if g['simulated'] else 'NO':<9}  {g['name']}")
        print("\nsimulated=NO: the rules list it but the engine does not implement it, so "
              "generated squads never carry it.")
    elif args.what == "metrics":
        for table, cols in data.items():
            print(f"{table}:")
            for c in cols:
                print(f"  {c['column']:<22}{c['doc']}")
    elif args.what == "tables":
        for t, n in data.items():
            print(f"  {t:<14}{n} columns")
    else:
        for k, v in data.items():
            print(f"  {k:<10}{v}")


def _cmd_describe(argv: list[str]) -> None:
    from foosim.sim import catalog, store

    ap = argparse.ArgumentParser(prog="foosim-analyze describe", description=_COMMANDS["describe"])
    ap.add_argument("name", help="a bot, setup, report, gear id or table name")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rules = load_rules()
    doc = store.schema_doc()
    gear = {g["id"]: g for g in catalog.gear(rules)}
    found = None
    for kind, table in (("bot", catalog.BOTS), ("setup", catalog.SETUPS),
                        ("report", catalog.REPORTS)):
        if args.name in table:
            found = {"kind": kind, "name": args.name, **table[args.name]}
    if found is None and args.name in gear:
        found = {"kind": "gear", **gear[args.name]}
    if found is None and args.name in doc:
        found = {"kind": "table", "name": args.name, "columns": doc[args.name]}
    if found is None:
        valid = [*catalog.BOTS, *catalog.SETUPS, *catalog.REPORTS, *gear, *doc]
        ap.error(_unknown("name", args.name, valid))
    if args.json:
        _json_out(found)
        return
    for k, v in found.items():
        if k == "columns":
            print("columns:")
            for c in v:
                print(f"  {c['column']:<22}{c['type']:<9}{c['doc']}")
        else:
            print(f"{k}: {v}")


def _cmd_schema(argv: list[str]) -> None:
    from foosim.sim import store

    ap = argparse.ArgumentParser(prog="foosim-analyze schema", description=_COMMANDS["schema"])
    ap.add_argument("--sql", action="store_true", help="print CREATE TABLE statements")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.sql:
        print(store.schema_sql())
    elif args.json:
        _json_out(store.schema_doc())
    else:
        for table, cols in store.schema_doc().items():
            print(f"{table}")
            for c in cols:
                print(f"  {c['column']:<22}{c['type']:<9}{c['doc']}")
            print()
        print("join key: (run_id, seed[, unit_id]).  `--sql` for DDL.  Example:\n"
              "  SELECT weapon_id, AVG(damage) FROM unit_weapons WHERE kind != 'synthetic' "
              "GROUP BY weapon_id;")


def _cmd_report(argv: list[str]) -> None:
    import sqlite3

    from foosim.sim import catalog, reports

    ap = argparse.ArgumentParser(prog="foosim-analyze report", description=_COMMANDS["report"])
    ap.add_argument("name", choices=list(catalog.REPORTS), help="; ".join(
        f"{k}: {v['summary']}" for k, v in catalog.REPORTS.items()))
    ap.add_argument("--db", required=True, metavar="SQLITE", help="file written by run --db")
    ap.add_argument("--run", type=int, action="append", metavar="ID",
                    help="run id (repeatable; default: the latest run)")
    ap.add_argument("--all", action="store_true", help="combine every run in the file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    from pathlib import Path

    if not Path(args.db).exists():
        ap.error(f"{args.db} does not exist; create it with `foosim-analyze run --db {args.db}`")
    db = sqlite3.connect(args.db)
    if args.all:
        runs = [r[0] for r in db.execute("SELECT run_id FROM runs ORDER BY run_id")]
    else:
        runs = args.run or [reports.latest_run(db)]
    result = reports.REPORT_FUNCS[args.name](db, load_rules(), runs)
    result["runs"] = runs
    if args.json:
        _json_out(result)
    else:
        print(reports.format_text(result, runs))


def _cmd_manifest(argv: list[str]) -> None:
    from foosim.sim import catalog, store

    argparse.ArgumentParser(prog="foosim-analyze manifest", description=_COMMANDS["manifest"]
                            ).parse_args(argv)
    flags = []
    for a in _run_parser()._actions:
        if not a.option_strings or a.dest == "help":
            continue
        flags.append({"flags": a.option_strings, "dest": a.dest,
                      "type": getattr(a.type, "__name__", "bool" if a.nargs == 0 else "str"),
                      "default": a.default, "choices": list(a.choices) if a.choices else None,
                      "repeatable": a.__class__.__name__ == "_AppendAction", "help": a.help})
    _json_out({
        "manifest_version": 1,
        "tool": "foosim-analyze",
        "guide": "docs/analysis-guide.md",
        "conventions": {
            "stdout": "results and JSON", "stderr": "progress and errors",
            "exit_codes": {"0": "ok", "2": "usage error (bad flag or unknown name)"},
            "determinism": "same seed + rules + options => identical rows",
            "damage_metric": "enemy damage only; friendly fire excluded",
        },
        "commands": {k: {"summary": v} for k, v in _COMMANDS.items()},
        "run_flags": flags,
        "bots": catalog.BOTS, "setups": catalog.SETUPS, "reports": catalog.REPORTS,
        "gear": catalog.gear(load_rules()), "schema": store.schema_doc(),
    })


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_overview())
        return
    cmds = {"run": _cmd_run, "list": _cmd_list, "describe": _cmd_describe,
            "schema": _cmd_schema, "report": _cmd_report, "manifest": _cmd_manifest}
    if argv[0] in cmds:
        cmds[argv[0]](argv[1:])
    elif argv[0].startswith("-"):
        _cmd_run(argv)  # legacy flat form: foosim-analyze --games 500 ...
    else:
        print(f"foosim-analyze: error: {_unknown('command', argv[0], cmds)}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":  # pragma: no cover
    main()
