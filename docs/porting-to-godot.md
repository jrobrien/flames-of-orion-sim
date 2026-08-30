# Porting the engine to Godot / C# (later)

This is the punch list for reusing `foosim.engine` behind a fancier UI. Keep it
updated as the effect registry grows. Rationale is in `PLAN.md §8`.

## What ports cleanly

- **Dataclasses** (`engine/state.py`) -> Godot `Resource` / `RefCounted` or C#
  records. Field names are the contract; keep them stable.
- **`data/rules.toml`** -> ship the same file (`ConfigFile`) or a baked JSON copy.
- **PRNG** (`engine/rng.py`) -> `splitmix64` is ~5 lines in any language. Same seed
  => identical replays across engines. This is why the engine does not use
  Python's `random`. **Conformance vector:** seed `0x0123456789ABCDEF`, first 12
  `d6` (via `randint(1,6)` rejection sampling over the 64-bit output) must be
  `[4, 6, 3, 3, 3, 5, 6, 4, 6, 4, 6, 1]` (`tests/test_rng.py::test_cross_language_golden_vector`).
- **`engine/hexgrid.py`** -> pure axial integer math; direct translation. Pixel
  helpers assume pointy-top, `size` = centre-to-corner.
- **`engine/visibility.py`** -> the `Board` protocol is four methods; port the
  active `mode` only. `multiray_2d` walks continuous segments by sampling every
  `0.1` hex — keep that constant identical if you want identical cover results.
- **Events** -> plain records; any UI can consume them.
- **Replays** (`sim/replay.py`) -> a `Replay` is `initial_state` (a `GameState`
  dict, RNG state included) + an ordered `decisions` list (each a
  `decision_to_dict` of one action / `ActivateUnit` / `EndActivation` / `Pass`).
  A port that reproduces `phases.step` + the PRNG replays these byte-for-byte.
  `state_hash` (sha256 of sorted-key JSON, first 16 hex) is the cross-impl
  conformance check; the committed goldens in `tests/data/replays/` are the
  fixtures.
- **Geometry** -> stays in axial hex ints. A continuous-space version can replace
  `hexgrid.py` with polygon intersection while leaving `resolve.py` untouched (it
  only calls `hexgrid.distance / los / cover / reachable`).

## What needs attention

- **Effect handlers** (`engine/effects.py`): each `@register("...")` token must be
  reimplemented. Inventory (fill in as they land):

  | token | weapon/upgrade/ammo | ported? |
  |---|---|---|
  | _TBD_ | | |

- **`apply()` control flow** in `resolve.py` -> translate step by step against
  `RULES.md §6`.
- **Dict field `statuses` / `modifiers`** -> pick typed equivalents in the target
  language.

## Transition option

Keep the Python engine; drive it from Godot over stdio JSON-RPC
(`phases.step` in, `(state, events)` out) until a native port is worth it.
