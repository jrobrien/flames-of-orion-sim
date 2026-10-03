# foosim - notes for agents

Rules-testing sandbox for the tabletop game *Flames of Orion*. Python 3.12, `uv`.

- Setup / checks: `uv sync --all-extras`, `uv run pytest`, `uv run ruff check src tests`.
- Running simulations and using results: **read `docs/analysis-guide.md`**, or ask the tool:
  `uv run foosim-analyze` (overview), `uv run foosim-analyze manifest` (all commands,
  flags, bots, setups, gear and the SQLite schema as one JSON document),
  `list bots|setups|gear`, `describe NAME`, `schema`. Everything is deterministic per seed.
- Damage metrics are **enemy damage only**; friendly fire (e.g. Rail Weapon lane hits) is
  flagged on the `damage` event and excluded - see `src/foosim/sim/gamestats.py`.
- Game rules data lives in `data/rules.toml` (prices, perks, frames); changing it changes
  the ruleset hash, so regenerate golden replays with `FOOSIM_REGEN_GOLDENS=1 uv run pytest
  tests/test_replay.py`.
- `docs/` is also the GitHub Pages site (browser sheet generator: `docs/index.html`,
  `app.js`, `data.js`); it is a standalone JS port that may drift from `foosim-sheet`.
- Don't commit or push unless asked.
