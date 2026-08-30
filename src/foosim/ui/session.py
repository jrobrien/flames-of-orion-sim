"""Interactive game driver for the UI. Pure Python - no imgui.

Unlike ``Timeline`` (which lazily pulls a fixed ``(state, events)`` stream for
Watch/Replay), a ``Session`` *owns* the game loop: each side is driven by a
``Policy`` or by ``"human"`` (decisions submitted from the UI). It keeps the full
frame history so you can scrub back to review, and ``rewind_to_cursor`` truncates
history to explore a different line.

Nav surface mirrors ``Timeline`` (``cursor``, ``current``, ``last_index``,
``complete``, ``step``, ``seek``, ``jump``, ``at_end``) so the same panels render
either driver.
"""

from __future__ import annotations

from collections.abc import Callable

from foosim.engine import phases
from foosim.engine.actions import IllegalAction
from foosim.engine.events import Event
from foosim.engine.state import GameState
from foosim.ui.timeline import Frame

__all__ = ["Session"]

_HUMAN = "human"
_GUARD = 20_000


class Session:
    def __init__(
        self,
        rules,
        initial_state: GameState,
        controllers: dict[int, object],
    ) -> None:
        self.rules = rules
        self.controllers = controllers  # side -> Policy | "human"
        self._live = initial_state.copy()
        self._frames: list[Frame] = [Frame(0, self._live, [])]
        self.cursor = 0
        if self._has_human():
            self.fast_forward_to_decision()

    # -- introspection -------------------------------------------------
    def _has_human(self) -> bool:
        return _HUMAN in self.controllers.values()

    @property
    def last_index(self) -> int:
        return len(self._frames) - 1

    live_index = last_index

    @property
    def loaded_count(self) -> int:
        return len(self._frames)

    @property
    def complete(self) -> bool:
        return self._live.winner is not None or self._live.phase == "done"

    @property
    def current(self) -> Frame:
        return self._frames[self.cursor]

    @property
    def live(self) -> GameState:
        return self._live

    def frame(self, i: int) -> Frame:
        return self._frames[max(0, min(i, self.last_index))]

    def at_live(self) -> bool:
        return self.cursor == self.last_index

    def at_end(self) -> bool:
        return self.complete and self.cursor == self.last_index

    def pending_side(self) -> int | None:
        return None if self.complete else phases.needs_decision(self._live)

    def pending_controller(self) -> object | None:
        sd = self.pending_side()
        return None if sd is None else self.controllers.get(sd, _HUMAN)

    def waiting_for_human(self) -> bool:
        return self.pending_controller() == _HUMAN

    # -- navigation (view only) -------------------------------------
    def seek(self, i: int) -> None:
        self.cursor = max(0, min(i, self.last_index))

    def step(self, n: int = 1) -> bool:
        new = max(0, min(self.cursor + n, self.last_index))
        moved = new != self.cursor
        self.cursor = new
        return moved

    def jump(self, direction: int, predicate: Callable[[Event], bool]) -> bool:
        i = self.cursor
        s = 1 if direction >= 0 else -1
        while 0 <= i + s <= self.last_index:
            i += s
            if self._frames[i].has_event(predicate):
                self.cursor = i
                return True
        return False

    # -- simulation --------------------------------------------------
    def _append(self, state: GameState, events: list[Event]) -> None:
        self._live = state
        self._frames.append(Frame(len(self._frames), state, list(events)))
        self.cursor = self.last_index  # follow live

    def _sim_one(self) -> str:
        """One ``phases.step``. -> 'stepped' | 'human' | 'done'."""
        if self.complete:
            return "done"
        sd = phases.needs_decision(self._live)
        if sd is None:
            self._append(*phases.step(self._live, None, self.rules))
            return "stepped"
        ctrl = self.controllers.get(sd, _HUMAN)
        if ctrl == _HUMAN:
            return "human"
        self._append(*phases.step(self._live, ctrl.decide(self._live), self.rules))
        return "stepped"

    def fast_forward_to_decision(self) -> None:
        """Run automatic phases + AI turns until a human is needed or the game
        ends. No-op if no side is human (Watch mode drives itself)."""
        if not self._has_human():
            return
        for _ in range(_GUARD):
            if self.complete or self.waiting_for_human():
                return
            if self._sim_one() != "stepped":
                return
        raise RuntimeError("fast_forward_to_decision exceeded the step guard")

    def advance_one(self) -> bool:
        """Playback/step tick. Scrubs forward through history when not live;
        otherwise simulates one step (returns False if blocked on a human)."""
        if not self.at_live():
            self.cursor += 1
            return True
        return self._sim_one() == "stepped"

    def load_all(self) -> None:
        if self._has_human():
            return  # can't auto-run a game that needs human input
        for _ in range(_GUARD):
            if self._sim_one() != "stepped":
                return
        raise RuntimeError("load_all exceeded the step guard")

    # -- human input ----------------------------------------------
    def submit(self, decision: object) -> None:
        if not self.at_live():
            raise IllegalAction("cannot act on a past frame - return to live first")
        if not self.waiting_for_human():
            raise IllegalAction("not waiting for a human decision")
        self._append(*phases.step(self._live, decision, self.rules))
        self.fast_forward_to_decision()

    def rewind_to_cursor(self) -> None:
        """Discard everything after the cursor and resume the game from there."""
        self._frames = self._frames[: self.cursor + 1]
        self._live = self._frames[-1].state.copy()
        self.cursor = self.last_index
        self.fast_forward_to_decision()
