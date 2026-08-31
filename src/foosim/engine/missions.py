"""Mission victory conditions - a small registry. Pure, engine-only.

``resolve_winner(state, rules)`` is called by ``phases`` after every step:

* a side with no live models loses immediately (``annihilation``);
* otherwise, at the end of the last round, the registered handler for
  ``state.mission`` decides.

Missions that need extra board state - Recovery (a Cargo token), Scavenge /
Burned to a Crisp (Loot Tokens, Shelters), Hold the Line (a Drop Ship marker) -
are **not implemented**: they require ``GameState`` fields that do not exist yet.
See PLAN.md M8.
"""

from __future__ import annotations

from collections.abc import Callable

__all__ = ["MISSIONS", "register", "resolve_winner"]

# handler(state, live_counts, rules) -> winner side (0/1) or -1 for a draw
MISSIONS: dict[str, Callable] = {}


def register(name: str):
    def deco(fn: Callable) -> Callable:
        MISSIONS[name] = fn
        return fn

    return deco


def _most_models(_state, live: dict[int, int], _rules) -> int:
    best = max(live.values())
    top = [sd for sd, n in live.items() if n == best]
    return top[0] if len(top) == 1 else -1


# Most models standing at the end of round 5.
register("warzone")(_most_models)
# "Noble Fight" - last player with a model; at the round limit, whoever has more.
register("last_standing")(_most_models)
# Only a wipe decides; the round limit is a draw.
register("annihilation")(lambda _s, _l, _r: -1)


def resolve_winner(state, rules) -> tuple[int | None, str | None]:
    """``(winner, reason)`` if the game is over, else ``(None, None)``.
    ``winner`` is 0, 1, or -1 (draw)."""
    live = {sd: len(state.live_units(sd)) for sd in state.sides()}
    alive = [sd for sd, n in live.items() if n > 0]
    if len(alive) <= 1:
        return (alive[0] if alive else -1), "annihilation"
    if state.round > rules.game["rounds"]:
        handler = MISSIONS.get(state.mission, MISSIONS["warzone"])
        return handler(state, live, rules), "round_limit"
    return None, None
