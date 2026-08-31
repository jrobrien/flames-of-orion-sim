# foosim

A desktop **rules-testing sandbox** for the tabletop mech skirmish game
*Flames of Orion*. Built to explore and stress-test changes to the combat rules:
play a battle by hand through a hex-grid UI, or run thousands of AI-vs-AI games and
diff the aggregates after a rule tweak.

> ### Play the real game
> *Flames of Orion* is a tabletop miniatures wargame by Stephen Hupfer. This
> project is a fan-made lab for tinkering with its rules — it is **not** a
> substitute for the game. If you enjoy poking at it here, buy the rulebook,
> paint some mechs, and play it on a table:
> **<https://underthedice.com/flamesoforion/>**

![foosim watching an AI-vs-AI urban 4v4](docs/img/foosim-ui.png)

*Watching a bot game (`uv run --extra ui foosim-ui`). The yellow line is a Rail
Weapon shot from `A2` raking down the board until an indestructible building stops
it — see the `rail_shot` / `rail_blocked` / `+1 heat` entries in the event log on
the right. Step/play controls are top-left; the unit roster and a per-hex
inspector dock on the sides.*

## Getting started

`foosim` isn't packaged — run it from a source checkout. It uses
[uv](https://docs.astral.sh/uv/) for the environment (Python 3.11+, pinned to
3.12 in `.python-version`).

```bash
# 1. install uv (once)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. clone and enter
git clone https://github.com/jrobrien/flames-of-orion-sim.git
cd flames-of-orion-sim

# 3. build the venv + install everything (engine + ui + analysis + dev tools)
uv sync --all-extras

# 4. sanity check
uv run pytest
```

`uv run <cmd>` runs inside the project venv without activating it; `uv sync` keeps
it in lockstep with `uv.lock`. Drop `--all-extras` for just the engine + dev
tools — the `ui` extra adds imgui-bundle, `analysis` adds numpy + pandas. `pytest`
and `ruff` are in the `dev` group and install by default.

### Run it

```bash
uv run --extra ui foosim-ui                     # watch a bot game (the screenshot above)
uv run foosim-autobattle --seed 1              # headless AI vs AI, event log only
uv run foosim-gen-unit --seed 5                # print random mech stat blocks
uv run foosim-analyze --games 500 --matchup greedy-vs-greedy          # bulk stats -> summary
uv run foosim-analyze --games 500 --override heat.second_action=2 --baseline base.csv  # A/B a rule
uv run --extra ui foosim-ui --replay tests/data/replays/skirmish_2v2_seed1.json  # scrub a saved game
```

### Play a game yourself

foosim is built for simulation and bulk analysis, but there is a playable mode.
`--play` hands you side 0 against the AI; `--hotseat` drives both sides on one
screen:

```bash
uv run --extra ui foosim-ui --play             # you are side 0 — urban 4v4, generated mechs
uv run --extra ui foosim-ui --play --skirmish  # the small fixed 2v2 board instead
uv run --extra ui foosim-ui --hotseat          # both sides human
```

Pick one of your units in the roster, choose an action in the **Actions** panel
(Move / Ranged / Melee / Disengage / Purge Heat), then click a hex or an enemy
token. The panel previews the to-hit number and expected damage before you
commit, and bolstered variants (run, charge, unleash hell, fury, …) appear as a
toggle on the action. Use the transport bar to step back and forth or save the
game as a replay.

**Status:** early. Design is in [`PLAN.md`](PLAN.md); the mechanics spec the engine
follows is [`RULES.md`](RULES.md). See `PLAN.md §7` for milestones.

## What it will do

- Select a unit, read its stats, choose an action, aim/move it on a 2D hex map
  with polygon-ish obstacles and square tokens. Turn-based.
- **Auto-battle:** headless AI vs AI to completion.
- **Replay & inspect:** scrub any battle, jump to crits / explosions / kills.
- **Bulk analysis:** `run_many` over a seed range, apply `--override` rule
  changes, compare runs.

## Design shape

- `foosim.engine` — pure, deterministic, **stdlib only**. `apply(state, action,
  rng, rules) -> (state, [events])`. Own `splitmix64` PRNG so replays are
  reproducible across languages.
- `foosim.ai` — bot policies (`engine` only).
- `foosim.sim` — run / replay / generate / analyze (`engine` + `ai`).
- `foosim.ui` — imgui-bundle front-end (the only place `imgui_bundle` is imported;
  nothing depends on it).

Rules numbers live in [`data/rules.toml`](data/rules.toml) so rule changes are data
edits, not code edits. The engine boundary is kept clean so the logic can back a
fancier Godot/C# UI later — see `PLAN.md §8`.

## Disclaimer

**Flames of Orion is © 2025 Stephen Hupfer.** This is an unofficial, fan-made
playtesting tool. It contains **no** rulebook text, art, or layout — only a
clean-room reimplementation of game mechanics (which are not copyrightable).
Buy the game: <https://underthedice.com/flamesoforion/>

## License

Code: MIT (see [`LICENSE`](LICENSE)). The *Flames of Orion* game and its rulebook
are the property of their author and are not covered by this license.
