"""Structured events emitted by the engine - the inspectable record of a game.

Every dice roll and sub-decision is an ``Event``. ``kind`` is a short string;
``data`` is a flat dict of JSON primitives. ``emit`` stamps a monotonic id from
``state.log_counter`` and appends to a sink list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Event", "emit"]


@dataclass
class Event:
    kind: str
    data: dict = field(default_factory=dict)
    id: int = -1

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, **self.data}

    @classmethod
    def from_dict(cls, d: dict) -> Event:
        d = dict(d)
        return cls(id=int(d.pop("id", -1)), kind=d.pop("kind"), data=d)


def emit(state, sink: list[Event], kind: str, /, **data) -> Event:
    """Append an Event to ``sink``, assigning it the next id from ``state``.

    ``kind`` is positional-only so events may carry a ``kind=`` data field.
    """
    e = Event(kind=kind, data=data, id=state.log_counter)
    state.log_counter += 1
    sink.append(e)
    return e
