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

## Quick start

Uses [uv](https://docs.astral.sh/uv/). Install it once:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then, from the repo root:

```bash
uv sync --all-extras                  # create .venv (Python per .python-version) + install
uv run pytest                         # engine tests

uv run foosim-autobattle --seed 1              # headless AI vs AI
uv run --extra ui foosim-ui --seed 3           # watch an AI game
uv run --extra ui foosim-ui --play --random    # play side 0, randomly generated mechs
uv run --extra ui foosim-ui --replay tests/data/replays/skirmish_2v2_seed1.json
uv run foosim-gen-unit --seed 5                # print random mech stat blocks
uv run foosim-analyze --games 500 --matchup greedy-vs-greedy   # bulk stats -> summary
uv run foosim-analyze --games 500 --override heat.second_action=2 --baseline <base.csv>  # A/B a rule
```

`uv run <cmd>` runs inside the project venv without activating it; `uv sync` keeps
it in lockstep with `uv.lock`. Drop `--all-extras` for just the engine + dev
tools — the `ui` extra adds imgui-bundle, `analysis` adds numpy + pandas. The dev
tools (`pytest`, `ruff`) are in the `dev` dependency group and install by default.

## Disclaimer

**Flames of Orion is © 2025 Stephen Hupfer.** This is an unofficial, fan-made
playtesting tool. It contains **no** rulebook text, art, or layout — only a
clean-room reimplementation of game mechanics (which are not copyrightable).
Buy the game: <https://underthedice.com/flamesoforion/>

## License

Code: MIT (see [`LICENSE`](LICENSE)). The *Flames of Orion* game and its rulebook
are the property of their author and are not covered by this license.
