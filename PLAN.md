# Development Plan — `foosim`

A desktop **rules-testing sandbox** for the tabletop mech game *Flames of Orion*.
Not a product; a lab. The point is to change combat rules and immediately see the
effect, by hand and in bulk.

Companion docs: [`RULES.md`](RULES.md) (the mechanics spec), `data/rules.toml`
(the tunable numbers).

---

## 1. Goals / non-goals

**Goals**
- Play a battle through a GUI: pick a unit, read its stats, choose an action, aim
  or move it on a 2D hex map with polygon-ish obstacles and square tokens.
- Turn-based, faithful to `RULES.md`, every dice roll inspectable.
- **Auto-battle**: AI vs AI to completion, headless, fast.
- **Replay & inspect**: scrub any battle forward/back, jump to crits/explosions.
- **Bulk analysis**: run thousands of games, tweak a rule, re-run, diff aggregates.
- Keep the rules logic **portable** — a future Godot/C# UI should be able to reuse
  it with a mechanical translation.

**Non-goals**
- Campaign layer (scars, salvage, credits, bunkers, XP).
- Multiplayer / netcode. 3+ players.
- Pretty graphics. Square tokens + flat-shaded hexes are the target.
- Matching the tabletop's continuous measurement exactly — we go hex (see
  `RULES.md §0`).

---

## 2. Guiding principles

1. **Pure, deterministic engine.** `foosim.engine` is plain dataclasses + pure
   functions. No I/O, no rendering, no globals, **stdlib only**. Given the same
   seed + setup + action list it reproduces a battle bit-for-bit.
2. **Own the RNG.** Do **not** use `random.Random` in the engine — its stream is
   not reproducible across languages. Implement a tiny `splitmix64` PRNG in
   `engine/rng.py` so replays survive a port to Godot/C#/Rust.
3. **`apply()` is the whole engine.**
   `apply(state, action, rules) -> (new_state, list[Event])`, no mutation of
   inputs. The RNG is threaded through `state.rng_state` (rebuilt each call,
   written back on the copy), so a snapshot fully captures RNG position. Every
   roll and sub-decision is emitted as a structured `Event`.
4. **Rules are data + a handler registry.** Numbers, tables, weapon/upgrade specs
   live in `data/rules.toml`. Simple numeric modifiers are read straight from it.
   Weird effects (Rail Weapon line attack, Virus Program, catastrophic results)
   are Python functions registered by string id; `rules.toml` still carries their
   tunable numbers. A test asserts every id in `rules.toml` has data or a handler.
5. **Portability boundary (hard rule).**
   `engine/` imports nothing but stdlib. `ai/` imports only `engine`. `sim/`
   imports `engine` + `ai` (may use numpy/pandas). `ui/` imports anything; nothing
   imports `ui`. `imgui_bundle` is imported **only** under `ui/`.
6. **Replays are the unit of work.** A battle = `(seed, setup, actions)`.
   Snapshots are *derived* by re-running, not stored (optionally cached). Re-running
   an old replay against edited `rules.toml` is the A/B experiment — divergence is
   the signal.
7. **Small state, so be lavish.** ~10 units, 5 rounds, ~80 steps/game. Deep-copy a
   full snapshot per step; never optimize the engine before it's correct.

---

## 3. Architecture

```
flames-of-orion-sim/
├── data/
│   └── rules.toml              # all tunable numbers, weapon/upgrade/ammo/table data
├── src/foosim/
│   ├── engine/                 # PURE. stdlib only. portable.
│   │   ├── rng.py              # splitmix64 PRNG + dice: d6, dN, ndN, d3, d2, d66, pool
│   │   ├── hexgrid.py          # axial coords: add, distance, neighbors, line, range,
│   │   │                       #   ring, reachable(blocked, cost), los(), cover()
│   │   ├── rules.py            # Ruleset: load rules.toml, typed accessors, content hash
│   │   ├── state.py            # dataclasses: Unit, WeaponInstance, TerrainHex, MapSpec,
│   │   │                       #   GameState (+ to_dict/from_dict, JSON-safe)
│   │   ├── actions.py          # Action dataclasses (Move, RangedAttack, ...) + Bolster
│   │   ├── events.py           # Event dataclasses (Roll, Hit, Save, Damage, Crit,
│   │   │                       #   Catastrophic, HeatGain, Overheat, Explode, ...)
│   │   ├── effects.py          # @register("line_attack") handler registry
│   │   ├── resolve.py          # apply(state, action, rules) -> (state, [Event])
│   │   ├── legal.py            # legal_actions(state, unit, rules); is_engaged; move_paths
│   │   └── phases.py           # round/phase/initiative/activation/heat driver;
│   │                           #   step(state, decision) -> (state, [Event]); win check
│   ├── ai/
│   │   ├── policy.py           # Policy protocol; RandomPolicy, GreedyPolicy
│   │   └── eval.py             # scoring helpers (hit chance, expected damage, threat)
│   ├── sim/
│   │   ├── replay.py           # Replay dataclass; save/load JSON; replay_game()
│   │   ├── autobattle.py       # run_game(setup, policy_a, policy_b, seed) -> Replay
│   │   ├── generate.py         # random Mech / Combat Unit generator (d6/d20/d8/d6/d66)
│   │   ├── setups.py           # canned MapSpec + deployment builders for tests/demos
│   │   └── analyze.py          # run_many(...) -> rows; summary; CSV; rule overrides
│   └── ui/                     # imgui-bundle. throwaway. the ONLY imgui importer.
│       ├── app.py              # main(): hello_imgui/immapp entry; mode switch
│       ├── mapview.py          # hex map draw-list render + mouse picking
│       ├── panels.py           # unit list, stat panel, action bar, event log
│       ├── replaybar.py        # timeline scrubber (play/pause/step, jump-to-event)
│       └── analysiswin.py      # ImPlot dashboards
├── scripts/                    # thin argparse wrappers around sim/*
│   ├── run_ui.py  run_autobattle.py  run_analysis.py  gen_unit.py
├── tests/
│   ├── data/                   # golden replays, fixed scenarios
│   └── test_*.py
└── docs/
    └── porting-to-godot.md
```

### Key types (sketch — finalize in M2)

As built in M2 (`engine/state.py`); ``Hex`` is a ``NamedTuple`` from ``hexgrid``.

```python
@dataclass
class WeaponInstance:
    weapon_id: str; kind: str            # "ranged" | "melee"; -> rules.toml
    ammo_id: str | None = None
    used_this_turn: bool = False
    disabled: bool = False               # catastrophic "Weapon Disabled"
    burnout: bool = False                # Power Weapon / Energy Sword degrade

@dataclass
class Unit:
    id: str; side: int; name: str; profile: str
    hp_max: int; ar: int; cs: int; speed: int; heat_limit: int; platforms: int
    hp: int = 0                          # __post_init__ -> hp_max if 0
    heat: int = 0
    pos: Hex = Hex(0, 0); facing: int = 0
    weapons: list[WeaponInstance] = ...
    upgrades: list[str] = ...
    modifiers: dict[str, int] = ...      # int deltas by stat name; Unit.stat(name) = base + delta
    statuses: dict[str, int] = ...       # flag / counter (lifetime managed by phases/resolve)
    reactive_armor_left: int = 0
    explodes / can_ram / ignores_terrain_on_move / heat_check_table   # baked from profile+upgrades
    activated: bool = False; out_of_action: bool = False

@dataclass
class TerrainHex:
    pos: Hex
    tags: set[str] = ...                 # {"blocking","cover","destructible","indestructible"}
    height: float = 1.0                  # structure height for center_25d
    damage_marks: int = 0; destroyed: bool = False

@dataclass
class MapSpec:                            # static geometry; live terrain is on GameState
    cols: int; rows: int; name: str = "untitled"
    elevation: dict[Hex, int] = ...       # sparse ground level
    deploy_zones: dict[int, tuple[Hex, ...]] = ...

@dataclass
class GameState:                          # also implements visibility.Board
    mapspec: MapSpec; mission: str; rng_state: int          # splitmix64 state
    round: int; phase: str; phase_index: int                # -> rules phase_order
    initiative: tuple[int, ...]; active_side: int; turn_in_phase: int
    units: dict[str, Unit]
    terrain: dict[Hex, TerrainHex]
    finished_first_last_round: int | None
    pass_tokens: dict[int, int]
    log_counter: int = 0
    winner: int | None = None; end_reason: str | None = None

# sim/replay.py (as built in M4)
@dataclass
class Replay:
    version: str = "1"
    ruleset_hash: str = ""     # Ruleset.content_hash at record time
    seed: int | None = None    # provenance only
    label: str = ""
    initial_state: dict = ...   # GameState.to_dict() - RNG state included
    decisions: list[dict] = ...  # decision_to_dict() for each non-None phase decision
    outcome: dict = ...         # {winner, end_reason, rounds, steps}
```

`record_game(state, policies, rules)` runs a game and captures the decisions.
`replay_game(replay, rules=None)` re-instantiates `initial_state` and re-feeds the
`decisions` through `autobattle.drive` -> `phases.step`. Because the RNG lives in
the state, no seed threading is needed. With `strict=True` (and the same ruleset)
it asserts the decision list is consumed exactly and the recorded outcome
matches. Passing a modified `rules` (`Ruleset.with_overrides`) runs the
counterfactual with `strict=False`; if a recorded decision becomes illegal
mid-divergence the replay stops cleanly.

---

## 4. UI plan (imgui-bundle)

Single window, `hello_imgui` docking layout. Three modes (radio in the toolbar):

- **Watch** — AI vs AI. Play/pause/step, speed slider. Auto-advances `phases.step`.
- **Interactive** — you drive one or both sides; the other can be a `Policy`.
  Hotseat supported.
- **Replay** — load a `Replay` JSON; the scrubber owns the clock.

Panels:

| Panel | Contents |
|---|---|
| **Map** (center) | hex grid via `imgui` draw-list; terrain hexes shaded by tag; square tokens with side colour, HP pips, heat bar, facing tick; overlays: reachable hexes (Move), range/LOS line (aim), blast radius, cover markers. Mouse: hover = hex info tooltip; click = pick destination/target for the pending action. |
| **Units** (left) | list grouped by side, selectable, shows HP/heat/activated; round/phase/initiative banner. |
| **Stats** (right, top) | selected unit: S/CS/AR/HP/HL/PF, heat vs limit bar, weapons (dmg, used?, disabled?), upgrades, active statuses/modifiers. |
| **Action** (right, mid) | buttons: Move / Ranged / Melee / Disengage / Purge; Bolster toggle + sub-mode combo; live preview for the pending action (hit chance, expected damage, HEAT cost, "will overheat"). Confirm / cancel. |
| **Log** (bottom) | structured event stream, newest last, colour-coded (hit/miss/crit/catastrophic/explode). Filter box. |
| **Replay bar** (bottom) | slider over snapshot index; ⏮⏸⏭ + step; buttons "next crit", "next explosion", "next kill". |
| **Analysis** (window) | ImPlot: win-rate bars, round-count histogram, heat-death rate, catastrophic-result distribution, avg survivors. Runs `analyze.run_many` on a thread. |

The UI never mutates `GameState` directly — it builds an `Action` / decision and
calls the engine, then re-renders from the returned state + events.

---

## 5. Analysis workflow (the reason this exists)

```
foosim-analyze --setup skirmish_2v2 --games 2000 --seed 1 \
               --policy-a greedy --policy-b greedy \
               --override to_hit.long_range_inches=8 \
               --override catastrophic.confirm=auto \
               --out out/lr8.csv
```

- `run_many` loops `run_game` over `seed0..seed0+n`, each producing a `Replay` +
  outcome; rows: `winner, rounds, survivors_a, survivors_b, crits, catastrophics,
  explosions, heat_deaths, total_damage`.
- `--override DOTTED.PATH=VALUE` deep-merges onto `rules.toml` before the run;
  the effective ruleset hash is recorded so results are traceable.
- Summary printed to stdout; CSV for diffing two runs (a helper `analyze.diff
  a.csv b.csv` prints deltas + a crude significance check).
- Same harness powers the in-app Analysis window.

---

## 6. Testing strategy

- `pytest`, seeded, no network.
- **Primitives:** hex identities (distance symmetry, line endpoints, range counts),
  `reachable()` on a small blocked map, PRNG determinism + rough uniformity.
- **Resolution:** fixed `GameState` + stubbed/seeded rng → assert the **exact**
  `Event` list for: clean hit, miss, AR-saved hit, natural-1 miss, natural-6 crit,
  confirmed catastrophic, cover +1, AP −1, Long Range −1, overheat death, explode
  that damages a neighbour, Rail Weapon line hitting two targets + a friendly.
- **Determinism:** run 50 seeded `run_game`s twice; assert identical decision lists
  and snapshot hashes. Golden `Replay` files in `tests/data/`; `replay_game`
  reproduces their snapshot hashes.
- **Content coverage:** enumerate every id in `rules.toml`; assert each resolves to
  a data effect or a registered handler.
- **Rules-as-data:** `Ruleset` round-trips; `content_hash` stable across loads,
  changes when a value changes.
- CI: GitHub Actions, `ruff check` + `pytest` on 3.11/3.12. UI not exercised in CI.

---

## 7. Milestones

Each milestone is shippable and leaves `main` green. Acceptance criteria are the
"done" test.

### M0 — Scaffold ✅ (this session)
Repo tree, `pyproject.toml` (src layout, hatchling, uv), `.python-version`,
`uv.lock`, `.gitignore` (PDF excluded), CI workflow (uv), `README.md`, `PLAN.md`,
`RULES.md`, `data/rules.toml` seeded with all frame/weapon/upgrade/ammo/table
numbers.
**Done when:** `uv sync`, `uv run ruff check .`, `uv run pytest` all succeed.

### M1 — Primitives ✅
`engine/rng.py` (splitmix64 + dice helpers, cross-language golden vector),
`engine/hexgrid.py` (axial math, `line`/`line_variants`, `range_hexes`, `ring`,
`spiral`, `reachable`, pixel/`corners` helpers), `engine/visibility.py`
(pluggable LOS/cover: `multiray_2d` default, `strict_center`, experimental
`center_25d`; `Board` protocol + `DictBoard`).
**Done when:** primitive tests green (`test_rng`, `test_hexgrid`,
`test_visibility`); all three modules import stdlib only.

### M2 — State + rules loader ✅
`engine/state.py`: `WeaponInstance`, `Unit` (battle-start effective stats +
`modifiers`/`statuses` deltas + baked behaviour flags + `stat()`), `TerrainHex`
(tag set + `height` + destruction marks), `MapSpec` (odd-r rectangle + sparse
`elevation` + deploy zones), `GameState` (round/phase pipeline state + live
terrain + `pass_tokens`; also implements the `visibility.Board` protocol). All
with `to_dict`/`from_dict`. `engine/rules.py` `Ruleset`: `tomllib` load, id-indexed
weapon/ammo/upgrade tables, typed accessors, `content_hash`, `with_overrides`
(dotted paths), load-time validation. `sim/setups.py`: `mech()` builder +
`skirmish_2v2`.
**Done when:** `GameState` → `to_dict` → JSON → `from_dict` is identity
(`test_state`, `test_setups`); `Ruleset` hash stable and moves under overrides
(`test_rules`); `skirmish_2v2` instantiates and round-trips.

### M3 — Resolution core (headless) ✅
`engine/actions.py` (5 actions + `ActivateUnit`/`EndActivation`/`Pass` + dict
round-trip), `engine/events.py` (`Event` + `emit`), `engine/legal.py`
(`legal_actions`, `is_engaged`, `move_paths` BFS), `engine/resolve.apply` for
Move/Ranged/Melee/Disengage/Purge (+ Bolster sub-modes: charge/run/snap_shot,
unleash_hell/focused_fire, fury/focused_strike/ram, dodge, reboot), the RULES §6
hit→crit→catastrophic→save chain, HEAT/overheat, Explode + chain, the 2d6
catastrophic table. `engine/phases.py` — data-driven pipeline over
`rules.phase_order` (unknown name → `phase_skipped`); initiative (+1 for last
round's first finisher, random tie-break), alternating activation with
`pass_tokens`, HEAT phase, round loop, victory (annihilation any time; Warzone /
draw at round limit). `ai/policy.RandomPolicy` (phase-aware). `sim/autobattle`
+ `foosim-autobattle` CLI.
**Done when:** scenario event tests pass (`test_resolve`); 20 seeds of 2v2
`RandomPolicy` run to a result (`test_phases`); same seed → identical final state
+ event stream; inserting `"bonus_melee"` into `phase_order` still completes.
Weapon/upgrade/ammo `special` behaviours beyond AP / max-range / flat damage are
`TODO(m7)`.

### M4 — Replay + determinism ✅
`sim/autobattle.drive` (shared game loop taking a `decide(state, side)` source).
`sim/replay.py`: `Replay`, `state_hash`, `save`/`load`, `record_game`,
`replay_game(strict=, rules=)`, `ReplayError`. Golden replays in
`tests/data/replays/` (`skirmish_2v2_seed{1,2,20}` = annihilation / side-1 win /
side-0 win); regenerate with `FOOSIM_REGEN_GOLDENS=1 uv run pytest -k golden`.
**Done when:** `test_determinism` (50 seeds ×2 identical state hash + event
stream; distinct seeds diverge), `test_replay` (record→replay reproduces;
save/load round-trips; goldens stable; strict mode catches truncated / leftover /
mismatched-outcome; counterfactual `with_overrides` replays non-strict without
crashing) all green.
*Perf note:* full suite ~50s, dominated by `legal_actions` (BFS + multiray LOS)
inside `RandomPolicy`. Fine for now; revisit if it bites during M5+.

### M5 — Minimal UI: Watch + Replay ✅ *(logic verified headless; window unverified)*
Pure/tested: `ui/timeline.py` (`Timeline`/`Frame` — lazy frame pull from any
`(state, events)` source, scrub/step/seek/jump-to-event), `ui/format.py` (event →
line + colour, unit stat lines, heat fraction), `ui/camera.py` (pan/zoom hex↔screen,
`fit`, `zoom_at`). imgui-only (not imported by tests): `ui/render.py` (hex grid +
terrain + square tokens w/ HP & heat bars + selection/hover), `ui/app.py`
(`build_watch`/`build_replay`, `UiState`, `foosim-ui` CLI). `sim/replay.iter_frames`
feeds the timeline. Layout is a **hello_imgui `RunnerParams` docking space** —
Transport / Units / Map / Stats / Event Log as dock nodes that reflow with the
window (fixed `first_use_ever` placement did not survive Hyprland's small→fullscreen).
Layout persists to `~/.config/foosim/foosim_ui.ini` under a stable title.
Watch mode plays a live AI game (lazy); Replay mode loads a `.json` and eager-loads.
Toolbar: play/pause/step/seek slider/fps/fit/next-crit/next-boom/next-kill. Map:
wheel-zoom, right/middle-drag pan, click-to-select; auto-fits until you touch it.
**Verified headless:** timeline lazy-load + navigation; format covers every event
kind in real games; camera round-trips + `fit`; `build_watch`/`build_replay`
construct and run a full game to `phase == "done"`; all `ui` modules import under
the `ui` extra; risky imgui-bundle API points checked by introspection.
**Not verified (needs a display):** actual window render / widget behaviour /
`hello_imgui.run`. Run `uv run --extra ui foosim-ui --seed 3` to confirm.

### M6 — Interactive play ✅ *(logic verified headless; window needs a visual check)*
- **Engine:** `resolve.plan_attack` + `AttackPlan` — the resolver and the UI now
  share one to-hit/AP path (`_effective_to_hit`, `_ap_for`); pure, no RNG. Reports
  legality/reason, effective CS, cover/long-range, hit/crit/catastrophic chance,
  save TN, ~expected damage through, HEAT cost.
- **Terrain:** `sim/setups.scatter_terrain` (seeded procedural buildings + cover,
  avoids deploy zones/units); `skirmish_2v2(terrain="scatter"|"fixed"|"none")`,
  scatter is the default — goldens regenerated.
- **`ui/session.Session`:** interactive driver. Each side is a `Policy` or
  `"human"`; keeps full frame history; `submit`, `fast_forward_to_decision`,
  `rewind_to_cursor` (truncate + resume a different line), scrub-is-view-only.
  Same nav surface as `Timeline`.
- **`ui/interaction.py`:** `compute_overlay` → reachable hexes/paths (move,
  ±run) or `plan_attack`-legal target ids; `submode` maps the bolster checkbox.
- **`ui/render.py`:** map overlays (reachable fill, hovered path, target rings,
  aim line) + `draw_tile_panel` (hex coords/offset, elevation, terrain, occupant,
  distance + LOS/cover from the selected unit).
- **`ui/app.py`:** Session-backed watch; `--play` (you = side 0) / `--hotseat`;
  Actions dock (activate → action buttons → click map to target → submit;
  bolster checkbox; live pre-roll preview); tile inspector in the Stats dock;
  "rewind to here" / ">> live" in the toolbar.
**Verified headless:** `plan_attack` numbers vs hand calc + vs resolver
`effective_cs`; Session watch/play/hotseat drive to completion, deterministic,
rewind/scrub semantics; overlay legality matches `plan_attack`; scatter terrain
seeded + never on deploy zones. **Not verified:** the imgui window itself — run
`uv run --extra ui foosim-ui --play --seed 3`.

**M6 follow-up — bolstered actions everywhere:**
- `legal.legal_actions(..., bolster=True)` (default) now emits the legal
  bolstered variants: run / charge / focused_fire / unleash_hell /
  focused_strike / fury / ram / dodge / reboot. `snap_shot` still omitted
  (engine stub — resolver accepts it but does nothing; TODO M7).
- `RandomPolicy(bolster_bias=0.75)` steers toward bolstered variants while a
  unit has HEAT headroom, backs off near the limit — table play bolsters almost
  every activation. `bolster_bias=0.0` reproduces the old no-bolster baseline.
  Goldens regenerated; determinism holds.
- UI: the bolster checkbox is now a per-action sub-mode combo (standard + the
  legal variants for that action); charge auto-targets an enemy adjacent to the
  chosen destination; ram shows fixed 1d3/1d3; Purge has separate
  "purge heat" / "reboot" buttons. Sub-mode resets to standard per action.

### M7 — Full content + generators
Wire every weapon/ammo/upgrade/frame via `engine/effects.py` registry + data.
`sim/generate.py` random Mech + legal 4-Mech Combat Unit (PF slots, cost, ammo,
call sign). `ai/policy.GreedyPolicy`.
**Done when:** content-coverage test passes; `foosim gen-unit` emits a legal unit.

### M8 — Missions + analysis dashboard
`sim/missions.py` pluggable objectives (all 6 + special objectives as optional
secret goals). `sim/analyze.py` `run_many` + `diff` + CSV; `--override`. In-app
`ui/analysiswin.py` ImPlot dashboard.
**Done when:** `foosim-analyze` runs 2000 games, writes CSV, prints a summary;
`--override to_hit.long_range_inches=8` visibly shifts the aggregate.

### M9 — Polish + portability
`docs/porting-to-godot.md` (state schema, effect-registry inventory, pure-vs-Python
notes). Tune `GreedyPolicy`, widen tests, README GIF.
**Done when:** the state schema + `RULES.md` + registry list are enough for someone
to reimplement `apply()` for one action in another language.

---

## 8. Porting to Godot later (why the boundary matters)

The engine is deliberately a plain state machine so a "fancy graphics" Godot/C#
front-end can reuse the *logic*:

- **Dataclasses → Godot** `Resource`/`RefCounted` or C# structs; field names match.
- **`rules.toml`** → ship the same file, parse with `ConfigFile`, or bake a JSON copy.
- **PRNG** — `splitmix64` is ~5 lines in any language; identical seeds → identical
  replays across engines. (This is why we don't use `random`.)
- **Events** are plain dicts/records → trivial for any UI to consume.
- **Geometry** stays in axial hex ints. A continuous-space Godot version can either
  keep `hexgrid` as-is over a hex board, or replace it with real polygon
  intersection while keeping `resolve.py` untouched (it only calls
  `hexgrid.distance/los/cover/reachable`).
- **Transition option:** keep the Python engine, drive it from Godot over stdio
  JSON-RPC (`phases.step` in, `(state, events)` out) until/unless a native port is
  worth it.

Keep `docs/porting-to-godot.md` updated as the effect registry grows — it's the
punch list for a port.

---

## 9. Tech / dependencies

- **Python ≥ 3.11** (`tomllib`, dataclass perf). Dev interpreter pinned in
  `.python-version` (3.12); CI matrixes 3.11 / 3.12 / 3.13.
- **[uv](https://docs.astral.sh/uv/)** for env + dependency management. `uv.lock`
  is committed; `uv sync` / `uv run` are the entry points (no manual venv).
- Engine + AI + replay: **stdlib only**.
- `sim/analyze.py`: `numpy`, `pandas` (`[analysis]` extra).
- `ui/`: `imgui-bundle` (bundles Dear ImGui + ImPlot + hello_imgui) (`[ui]` extra).
- Dev: `pytest`, `ruff` (`dev` dependency group, installed by default).
- Build: `hatchling`, src layout. Console scripts: `foosim-ui`, `foosim-autobattle`,
  `foosim-analyze`, `foosim-gen-unit`.

## 10. Open questions (see also `RULES.md §18`)

- **LOS/cover** — approach decided in M1 (`engine/visibility.py`, pluggable,
  default `multiray_2d`; see `RULES.md §5.1`). Still open: `center_25d` semantics,
  where map elevation + structure-height data lives (M2 schema), hand-validation
  against real tabletop situations, tuning `sample_corner_fraction`.
- Whether to snapshot every step eagerly in the UI (memory ~KBs/game, fine) or
  lazily re-sim on scrub-back (cheaper, simpler cache invalidation). Default:
  eager list, capped ring buffer in Watch mode.
- Elevation/vertical movement rules (cost, gaps, VTOL, falling) — `MapSpec` gets
  `elevation` + terrain `height` at M2 for `center_25d`; movement rules that use
  them are deferred to post-M9.
- `GreedyPolicy` sophistication — keep a frozen baseline for regression; iterate a
  separate `policy_v2` so analysis runs stay comparable over time.

## 11. Anticipated rule experiments (design accommodates these now)

The point of the project is to change rules cheaply. Known candidates and where
they slot in:

- **Bonus end-of-round close-combat phase.** Add `"bonus_melee"` to
  `[game] phase_order` (`data/rules.toml`); bind it to a handler in
  `engine/phases.py` that offers eligible units a Melee decision; add a matching
  branch to each `Policy` (the contract is phase-aware by design). Replay,
  determinism, and analysis need no changes — it's just more decision records and
  another column the analyzer can bucket. Open sub-questions when concrete: who is
  eligible (any Engaged unit? both sides? initiative order?), does it generate
  HEAT, can it be Bolstered, does it interact with Activation tokens.
- **LOS fidelity dial.** `[visibility] mode` + `sample_corner_fraction` are
  runtime knobs; `--override` can sweep them in analysis to see how much LOS
  generosity moves win rates.
- **Any numeric tweak** (to-hit modifiers, HEAT tables, catastrophic effects,
  weapon stats) is a `data/rules.toml` edit or an `--override`; the engine reads,
  never hardcodes.
- **New actions / statuses** land in `engine/actions.py` + `engine/effects.py`
  (registry) without touching the phase driver.
