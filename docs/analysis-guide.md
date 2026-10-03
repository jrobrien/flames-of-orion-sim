# Analysis guide: running bulk simulations and using the data

`foosim-analyze` plays many AI-vs-AI games, summarizes them, and (with `--db`) stores
per-mech and per-weapon detail in SQLite for analysis here or in another program.

```bash
uv run foosim-analyze                  # overview: commands, bots, setups, workflows
uv run foosim-analyze <command> --help # flags for one command
```

For tools and agents: `foosim-analyze manifest` prints everything (commands, flags,
bots, setups, gear, database schema) as one JSON document; `list`, `describe` and
`schema` take `--json`. Results go to stdout, progress and errors to stderr; usage
errors exit 2 and name the valid values ("did you mean ...").

## Concepts

- **Game seed.** Games are numbered `seed .. seed+N-1` (`--seed`, default 0). A game's
  squads, map and dice all derive from its seed, so the same seed + rules + options
  reproduces the same games exactly, serial or parallel (`-j`).
- **Setups** (`--setup`, `list setups`): `urban` (default, 4v4 on a 30x30 city),
  `scatter` (4v4, open ground), `skirmish` (fixed 2v2, fast, for rule A/B tests).
- **Squads.** In `urban` / `scatter` each side fields a quick-play squad: a Heavy leader
  with one perk, two Mediums and a Light, rolled on the Black Market tables using only
  gear the simulator implements (`list gear` shows which; `simulated=NO` items are never
  generated).
- **Bots** (`--matchup BOT0-vs-BOT1`, `list bots`, `describe greedy`): `greedy` scores
  each action and plays the best (default for analysis); `random` plays uniformly among
  legal actions (a baseline). Results depend on the bot - cross-check important
  findings with a second matchup.

## Recipe: which weapons and builds deal the most damage?

```bash
uv run foosim-analyze run --games 2000 --db results.sqlite --label baseline
uv run foosim-analyze report weapons  --db results.sqlite
uv run foosim-analyze report frames   --db results.sqlite
uv run foosim-analyze report upgrades --db results.sqlite
```

2000 games is about a minute on 16 cores. Reports use the latest run unless you pass
`--run N` (repeatable) or `--all`; add `--json` for machine-readable output.

**The metric.** *Damage dealt* is hull damage that got through armor onto an **enemy**
mech, booked by source:

| column / weapon | what it is |
|---|---|
| `damage_weapon` (a weapon id in `unit_weapons`) | the weapon that fired |
| `explosion` | a mech dying and exploding (credited to the mech that exploded, not its killer) |
| `self_destruct` | the Self Destruct upgrade; a separate synthetic weapon from `explosion` |
| `damage_other` | rams and terrain collapses |
| `friendly_damage` | damage to the dealer's own side (Rail Weapon lane hits on teammates, blasts catching friends, ram self-damage). **Excluded from every damage-dealt metric**; kept only for reference |

`report weapons` also gives hit rate, damage per attack, price, and damage per
10,000$ (cost-efficiency), with a 95% interval over mech-games.

## Isolating variables

A mech's damage depends on its frame, its other gear, its teammates, the enemy squad, the
map and luck, so raw averages are confounded. Tools for controlling that (all on
`urban`/`scatter`):

| flag | effect |
|---|---|
| `--squad-seed N` | pin **both** squads to seed N: the same two squads in every game |
| `--squad-seed-0 N` / `--squad-seed-1 N` | pin one side; the other still varies with the game seed |
| `--mirror` | side 1 copies side 0's squad each game (squads vary per game): build differences vanish, leaving bot, luck and position |
| `--terrain-seed N` | pin the map |

Examples:

```bash
# how does one fixed squad fare against a random field? (1000 games)
uv run foosim-analyze run --games 1000 --squad-seed-0 7 --db ctrl.sqlite --label squad7
# is there a first-side advantage with identical squads?
uv run foosim-analyze run --games 1000 --mirror --db mirror.sqlite
# same fight on one map, only the dice vary
uv run foosim-analyze run --games 500 --squad-seed 3 --terrain-seed 3
```

For a stronger test, compare two pinned squads that differ in one slot using the same
game seeds (common random numbers). Single-slot-swap setups are not built in yet; for
now generate the two squads by seed and look for a pair that differs as you want
(`foosim-gen-unit`), or fit a regression on the `units` / `unit_weapons` tables of a
large observational run (damage ~ frame + weapon counts + upgrades).

## The data

`--db FILE` appends one **run** per invocation (so you can keep baseline and variant in
one file and diff them by `run_id`):

| table | one row per | has |
|---|---|---|
| `runs` | invocation | args, ruleset hash, git commit, bots, setup, pinned seeds |
| `games` | game | winner, rounds, survivors, totals (the `--out` CSV columns) |
| `units` | mech per game | build (frame, final S/CS/AR/HL/HP/PF, cost, perk, upgrades) and results (damage by source, damage taken, kills, attacks/hits/crits, heat, survival, round and cause of loss) |
| `unit_weapons` | weapon slot per mech per game | weapon, ammo, attacks, hits, crits, damage; plus rows for synthetic weapons |
| `unit_upgrades` | upgrade per mech per game | for easy joins |

`uv run foosim-analyze schema` prints every column with its meaning; `--sql` gives DDL.
Join on `(run_id, seed[, unit_id])`. Examples:

```sql
-- mean enemy damage per mech-game by weapon, with usage
SELECT weapon_id, COUNT(*) AS slots, ROUND(AVG(damage), 2) AS avg_damage
FROM unit_weapons WHERE kind != 'synthetic' AND run_id = 1 GROUP BY weapon_id ORDER BY 3 DESC;

-- damage per 10,000$ by frame
SELECT frame, ROUND(AVG(damage_weapon + damage_explosion + damage_self_destruct
                        + damage_other) * 10000.0 / AVG(cost), 3) AS dmg_per_10k
FROM units WHERE run_id = 1 GROUP BY frame;

-- do leaders with a perk do better?
SELECT perk, COUNT(*), ROUND(AVG(damage_weapon), 2) FROM units WHERE leader = 1 GROUP BY perk;
```

Open the file from Python (`sqlite3`, `pandas.read_sql_query`), R (`RSQLite`), DuckDB
(`ATTACH 'results.sqlite'`) or the `sqlite3` CLI.

## A/B-testing a rule

```bash
uv run foosim-analyze run --games 1000 --out base.csv
uv run foosim-analyze run --games 1000 --override heat.second_action=2 --baseline base.csv
```

Both runs use the same seeds, so squads, maps and starting dice match; the printed
difference isolates the rule change as far as the bots' behaviour allows. Add
`--db results.sqlite` to both to keep per-mech detail.

## Caveats

- **Bot-dependent.** Greedy scores by expected damage, so it can favour weapons that look
  good to it. Check with `--matchup random-vs-random`.
- **Simulated gear only.** Items marked `simulated=NO` in `list gear` are never generated
  and cannot be evaluated until the engine implements them.
- **Confidence intervals** treat mechs as independent; teammates and opponents are not.
  Prefer many games and isolation over trusting a small gap.
- **Kills** are credited to the source of the last damage (approximate for
  catastrophic-only deaths).
- The Heavy leader's perk is limited to ones the sim can apply (HEAT Expert, Hydraulics
  Overhaul); other perks need engine support first.
