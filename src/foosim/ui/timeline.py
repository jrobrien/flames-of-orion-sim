"""A scrubbable timeline of game frames. Pure Python - no imgui, no display.

A ``Frame`` is the state after step *i* plus that step's events (frame 0 is the
initial state with no events). Frames are pulled lazily from a source iterator of
``(GameState, [Event])`` - which is exactly what ``autobattle.drive`` and
``replay.iter_frames`` yield - so Watch mode can play "live" while Replay mode
loads everything up front.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field

from foosim.engine.events import Event
from foosim.engine.state import GameState

__all__ = ["Frame", "Timeline"]


@dataclass
class Frame:
    index: int
    state: GameState
    events: list[Event] = field(default_factory=list)
    decision: dict | None = None  # the decision that produced this frame (Session only)

    def event_kinds(self) -> frozenset[str]:
        return frozenset(e.kind for e in self.events)

    def has_event(self, predicate: Callable[[Event], bool]) -> bool:
        return any(predicate(e) for e in self.events)


class Timeline:
    def __init__(self, initial: GameState, source: Iterable[tuple[GameState, list[Event]]]):
        first = initial.copy() if hasattr(initial, "copy") else initial
        self._frames: list[Frame] = [Frame(0, first, [])]
        self._src: Iterator = iter(source)
        self._exhausted = False
        self.cursor = 0

    # -- loading --------------------------------------------------------
    def _pull_one(self) -> bool:
        if self._exhausted:
            return False
        try:
            state, events = next(self._src)
        except StopIteration:
            self._exhausted = True
            return False
        self._frames.append(Frame(len(self._frames), state, list(events)))
        return True

    def _load_to(self, idx: int) -> None:
        while len(self._frames) <= idx and self._pull_one():
            pass

    def load_all(self) -> None:
        while self._pull_one():
            pass

    @property
    def loaded_count(self) -> int:
        return len(self._frames)

    @property
    def complete(self) -> bool:
        return self._exhausted

    @property
    def last_index(self) -> int:
        return len(self._frames) - 1

    # -- navigation ---------------------------------------------------
    @property
    def current(self) -> Frame:
        return self._frames[self.cursor]

    def frame(self, idx: int) -> Frame:
        self._load_to(idx)
        return self._frames[max(0, min(idx, self.last_index))]

    def frames_through_cursor(self) -> list[Frame]:
        return self._frames[: self.cursor + 1]

    def seek(self, idx: int) -> None:
        idx = max(0, idx)
        self._load_to(idx)
        self.cursor = max(0, min(idx, self.last_index))

    def step(self, n: int = 1) -> bool:
        target = self.cursor + n
        if n > 0:
            self._load_to(target)
        new = max(0, min(target, self.last_index))
        moved = new != self.cursor
        self.cursor = new
        return moved

    def advance_one(self) -> bool:
        """Uniform with ``Session.advance_one`` - one step forward, loading lazily."""
        return self.step(1)

    def at_end(self) -> bool:
        return self._exhausted and self.cursor == self.last_index

    def jump(self, direction: int, predicate: Callable[[Event], bool]) -> bool:
        """Move the cursor to the next/prev frame whose events match. Returns
        whether a match was found."""
        i = self.cursor
        step = 1 if direction >= 0 else -1
        while True:
            i += step
            if i < 0:
                return False
            self._load_to(i)
            if i > self.last_index:
                return False
            if self._frames[i].has_event(predicate):
                self.cursor = i
                return True
