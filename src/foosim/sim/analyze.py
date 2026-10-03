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
from foosim.sim.generate import random_setup
from foosim.sim.setups import skirmish_2v2

__all__ = [
    "GameRow",
    "diff",
    "parse_override",
    "read_csv",
    "run_many",
    "run_parallel",
    "run_one",
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


def run_one(setup, policies, rules: Ruleset, seed: int) -> GameRow:
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
    return GameRow(
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


def _run_seed(seed: int) -> GameRow:
    assert _WORKER is not None
    rules, make_setup, make_policies = _WORKER
    return run_one(make_setup(seed), make_policies(seed), rules, seed)


def run_parallel(
    rules: Ruleset, setup: str, p0: str, p1: str, *, n: int, seed0: int = 0,
    jobs: int | None = None, progress: bool = False, setup_opts: dict | None = None,
) -> list[GameRow]:
    """``run_many`` for named setups/policies across worker processes. Each game depends
    only on its seed, so rows come back in seed order and are identical to a serial
    run. ``jobs`` of ``None`` uses every CPU; ``1`` stays in-process."""
    seeds = range(seed0, seed0 + n)
    jobs = min(jobs or os.cpu_count() or 1, n) or 1
    if jobs <= 1:
        make_setup, make_policies = _factories(rules, setup, p0, p1, setup_opts)
        return run_many(make_setup, make_policies, rules, n=n, seed0=seed0)
    rows: list[GameRow] = []
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


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Bulk Flames of Orion auto-battle analysis")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0, help="first seed (games use seed..seed+N)")
    ap.add_argument("--setup", choices=list(_SETUPS), default="urban")
    ap.add_argument("--matchup", default="greedy-vs-greedy",
                    help="p0-vs-p1, each of: " + " / ".join(_POLICIES))
    ap.add_argument("--override", action="append", default=[], metavar="PATH=VALUE",
                    help="rules.toml override (repeatable)")
    ap.add_argument("--squad-seed", type=int, metavar="N",
                    help="pin BOTH squads to this seed (same squads every game; same value "
                         "on both sides = mirror match)")
    ap.add_argument("--squad-seed-0", type=int, metavar="N", help="pin side 0's squad only")
    ap.add_argument("--squad-seed-1", type=int, metavar="N", help="pin side 1's squad only")
    ap.add_argument("--terrain-seed", type=int, metavar="N", help="pin the map to this seed")
    ap.add_argument("-j", "--jobs", type=int, default=None, metavar="N",
                    help="worker processes (default: all CPUs; 1 = run in-process)")
    ap.add_argument("--out", metavar="CSV", help="write per-game rows here")
    ap.add_argument("--baseline", metavar="CSV", help="prior --out CSV to diff against")
    args = ap.parse_args(argv)

    rules = load_rules()
    if args.override:
        rules = rules.with_overrides(dict(parse_override(o) for o in args.override))

    p0_name, _, p1_name = args.matchup.partition("-vs-")
    setup_opts = {
        "squad_seed_0": args.squad_seed if args.squad_seed_0 is None else args.squad_seed_0,
        "squad_seed_1": args.squad_seed if args.squad_seed_1 is None else args.squad_seed_1,
        "terrain_seed": args.terrain_seed,
    }
    setup_opts = {k: v for k, v in setup_opts.items() if v is not None}
    if setup_opts and args.setup == "skirmish":
        ap.error("squad/terrain seeds apply to the urban and scatter setups only")
    rows = run_parallel(
        rules, args.setup, p0_name, p1_name, n=args.games, seed0=args.seed,
        jobs=args.jobs, progress=sys.stderr.isatty(), setup_opts=setup_opts,
    )
    summary = summarize(rows)

    print(f"{args.matchup} on {args.setup}  ({args.games} games, ruleset {rules.content_hash})")
    if args.override:
        print("  overrides: " + ", ".join(args.override))
    print(_fmt(summary))

    if args.out:
        write_csv(rows, args.out)
        print(f"  wrote {args.out}")
    if args.baseline:
        base = summarize(read_csv(args.baseline))
        print(f"\nvs baseline {args.baseline}:")
        print(_fmt(diff(base, summary)))


if __name__ == "__main__":  # pragma: no cover
    main()
