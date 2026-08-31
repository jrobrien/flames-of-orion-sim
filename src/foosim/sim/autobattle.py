"""Run a whole game headless by driving ``engine.phases`` with a decision source."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator

from foosim.engine import phases
from foosim.engine.events import Event
from foosim.engine.state import GameState

__all__ = ["drive", "run_game"]

# decide(state, side) -> a decision. May raise StopIteration to end the game early
# (used by replay when its recorded decisions run out).
DecideFn = Callable[[GameState, int], object]


def drive(
    state: GameState,
    decide: DecideFn,
    rules,
    *,
    max_steps: int = 20_000,
) -> Iterator[tuple[GameState, list[Event]]]:
    """Advance a game to completion, yielding ``(state, events)`` after each step.

    ``decide`` supplies each activation-phase decision; automatic phases pass
    ``None``. This is the single game loop shared by ``run_game``,
    ``replay.record_game``, and ``replay.replay_game``.
    """
    s = state
    steps = 0
    while s.winner is None and s.phase != "done":
        if steps >= max_steps:
            raise RuntimeError(f"drive exceeded {max_steps} steps without terminating")
        side = phases.needs_decision(s)
        if side is None:
            decision = None
        else:
            try:
                decision = decide(s, side)
            except StopIteration:
                return
        s, evs = phases.step(s, decision, rules)
        steps += 1
        yield s, evs


def run_game(
    state: GameState,
    policies: dict[int, object],
    rules,
    *,
    max_steps: int = 20_000,
) -> tuple[GameState, list[Event], int]:
    final, events, steps = state, [], 0
    for s, evs in drive(state, lambda st, sd: policies[sd].decide(st), rules, max_steps=max_steps):
        final, steps = s, steps + 1
        events.extend(evs)
    return final, events, steps


def main(argv: list[str] | None = None) -> None:
    from foosim.ai.policy import RandomPolicy
    from foosim.engine.rules import load
    from foosim.sim.generate import random_setup
    from foosim.sim.setups import skirmish_2v2

    ap = argparse.ArgumentParser(description="Headless Flames of Orion auto-battle")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--random", action="store_true", help="randomly generated combat units")
    args = ap.parse_args(argv)

    rules = load()
    gs = random_setup(rules, seed=args.seed) if args.random else skirmish_2v2(rules, seed=args.seed)
    pols = {
        0: RandomPolicy(rules, seed=args.seed * 2 + 1),
        1: RandomPolicy(rules, seed=args.seed * 2 + 2),
    }
    final, events, steps = run_game(gs, pols, rules)

    print(
        f"winner={final.winner} reason={final.end_reason} "
        f"round={min(final.round, rules.game['rounds'])} steps={steps} events={len(events)}"
    )
    for sd in final.sides():
        alive = [u.id for u in final.live_units(sd)]
        print(f"  side {sd}: {len(alive)} standing {alive}")


if __name__ == "__main__":  # pragma: no cover
    main()
