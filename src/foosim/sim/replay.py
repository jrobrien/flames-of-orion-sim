"""Replays: record a game as (initial state + decision list), re-simulate it.

A game is fully determined by its initial ``GameState`` (RNG state included) and
the ordered list of activation-phase decisions. So a ``Replay`` stores exactly
that, plus the ruleset hash it was recorded against and the outcome it produced.

``replay_game(replay, rules)`` re-simulates. Passing a *different* ``rules`` (e.g.
``Ruleset.with_overrides(...)``) runs the counterfactual - it may diverge, so use
``strict=False`` there.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from foosim.engine.actions import IllegalAction, decision_from_dict, decision_to_dict
from foosim.engine.rules import Ruleset
from foosim.engine.rules import load as load_rules
from foosim.engine.state import GameState
from foosim.sim.autobattle import drive

__all__ = [
    "REPLAY_VERSION",
    "Replay",
    "ReplayError",
    "iter_frames",
    "load",
    "record_game",
    "replay_game",
    "save",
    "state_hash",
]

REPLAY_VERSION = "1"


class ReplayError(RuntimeError):
    pass


def state_hash(state: GameState) -> str:
    blob = json.dumps(state.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


@dataclass
class Replay:
    version: str = REPLAY_VERSION
    ruleset_hash: str = ""
    seed: int | None = None
    label: str = ""
    initial_state: dict = field(default_factory=dict)
    decisions: list[dict] = field(default_factory=list)
    outcome: dict = field(default_factory=dict)

    def state(self) -> GameState:
        return GameState.from_dict(self.initial_state)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "ruleset_hash": self.ruleset_hash,
            "seed": self.seed,
            "label": self.label,
            "initial_state": self.initial_state,
            "decisions": self.decisions,
            "outcome": self.outcome,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Replay:
        return cls(
            version=d.get("version", REPLAY_VERSION),
            ruleset_hash=d.get("ruleset_hash", ""),
            seed=d.get("seed"),
            label=d.get("label", ""),
            initial_state=d.get("initial_state", {}),
            decisions=list(d.get("decisions", [])),
            outcome=d.get("outcome", {}),
        )


def save(replay: Replay, path: str | Path) -> None:
    Path(path).write_text(json.dumps(replay.to_dict(), indent=2, sort_keys=True) + "\n")


def load(path: str | Path) -> Replay:
    return Replay.from_dict(json.loads(Path(path).read_text()))


def record_game(
    initial_state: GameState,
    policies: dict[int, object],
    rules: Ruleset,
    *,
    seed: int | None = None,
    label: str = "",
    max_steps: int = 20_000,
) -> tuple[GameState, list, Replay]:
    rep = Replay(
        ruleset_hash=rules.content_hash,
        seed=seed,
        label=label,
        initial_state=initial_state.to_dict(),
    )
    events: list = []
    final, steps = initial_state, 0

    def decide(state, side):
        d = policies[side].decide(state)
        rep.decisions.append(decision_to_dict(d))
        return d

    for s, evs in drive(initial_state, decide, rules, max_steps=max_steps):
        final, steps = s, steps + 1
        events.extend(evs)

    rep.outcome = {
        "winner": final.winner,
        "end_reason": final.end_reason,
        "rounds": min(final.round, rules.game["rounds"]),
        "steps": steps,
    }
    return final, events, rep


def _replay_decider(replay: Replay):
    """Returns ``(decide, counter)`` where ``counter["i"]`` tracks decisions used.
    ``decide`` raises ``StopIteration`` once the recorded decisions run out."""
    counter = {"i": 0}

    def decide(state, side):
        if counter["i"] >= len(replay.decisions):
            raise StopIteration
        d = replay.decisions[counter["i"]]
        counter["i"] += 1
        return decision_from_dict(d)

    return decide, counter


def iter_frames(replay: Replay, rules: Ruleset | None = None):
    """Yield ``(GameState, [Event])`` per step for ``replay`` - feeds the UI
    timeline. Stops when the game ends or the recorded decisions run out."""
    rules = rules or load_rules()
    decide, _ = _replay_decider(replay)
    yield from drive(replay.state(), decide, rules)


def replay_game(
    replay: Replay,
    rules: Ruleset | None = None,
    *,
    strict: bool = True,
    max_steps: int = 20_000,
) -> tuple[GameState, list]:
    """Re-simulate ``replay``. With ``strict`` (default) and the *same* ruleset,
    asserts the decision list is consumed exactly and the outcome matches."""
    rules = rules or load_rules()
    same_ruleset = not replay.ruleset_hash or replay.ruleset_hash == rules.content_hash
    if strict and not same_ruleset:
        warnings.warn(
            f"replaying against ruleset {rules.content_hash} but recorded against "
            f"{replay.ruleset_hash}; outcome may diverge",
            stacklevel=2,
        )

    decide, counter = _replay_decider(replay)
    final, events = replay.state(), []
    try:
        for s, evs in drive(final, decide, rules, max_steps=max_steps):
            final = s
            events.extend(evs)
    except IllegalAction:
        # A recorded decision became illegal - a genuine regression when the
        # ruleset is unchanged, but the expected end state of a counterfactual
        # replay that has diverged. Stop cleanly in the latter case.
        if strict and same_ruleset:
            raise

    finished = final.winner is not None or final.phase == "done"
    if strict and same_ruleset:
        if not finished:
            raise ReplayError(
                f"replay exhausted after {counter['i']}/{len(replay.decisions)} decisions "
                "but the game had not ended"
            )
        leftover = len(replay.decisions) - counter["i"]
        if leftover:
            raise ReplayError(f"{leftover} decisions left over after the game ended")
        want = replay.outcome.get("winner")
        if replay.outcome and want != final.winner:
            raise ReplayError(
                f"outcome mismatch: recorded winner={want}, replay winner={final.winner}"
            )

    return final, events
