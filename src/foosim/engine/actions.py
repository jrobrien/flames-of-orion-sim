"""Actions and activation-control decisions. Pure data.

``resolve.apply`` executes the five *actions*; ``phases.step`` also consumes the
*control* decisions (``ActivateUnit`` / ``EndActivation`` / ``Pass``). All carry
``to_dict`` / ``from_dict`` via :func:`decision_to_dict` / :func:`decision_from_dict`
so a replay is just an ordered list of these.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from foosim.engine.hexgrid import Hex

__all__ = [
    "ACTION_TYPES",
    "ActivateUnit",
    "DisengageAction",
    "EndActivation",
    "IllegalAction",
    "MeleeAttackAction",
    "MoveAction",
    "Pass",
    "PurgeHeatAction",
    "RangedAttackAction",
    "decision_from_dict",
    "decision_to_dict",
    "is_action",
]


class IllegalAction(Exception):
    """Raised by the engine when an action violates the rules. Policies/UI are
    expected to submit only legal actions (see ``engine.legal``)."""


@dataclass
class MoveAction:
    unit_id: str
    path: list[Hex]  # [current_pos, ..., dest]; each step adjacent
    bolster: str | None = None  # "charge" | "run" | "snap_shot"
    melee_target: str | None = None  # charge
    melee_weapon_index: int | None = None  # charge
    shot_target: str | None = None  # snap_shot
    shot_weapon_index: int | None = None  # snap_shot
    shot_at: int = -1  # snap_shot: path index to fire from; -1 = from the destination


@dataclass
class RangedAttackAction:
    unit_id: str
    target_id: str
    weapon_index: int
    bolster: str | None = None  # "unleash_hell" | "focused_fire"


@dataclass
class MeleeAttackAction:
    unit_id: str
    target_id: str
    weapon_index: int
    bolster: str | None = None  # "fury" | "focused_strike" | "ram"


@dataclass
class DisengageAction:
    unit_id: str
    path: list[Hex]
    bolster: str | None = None  # "dodge"


@dataclass
class PurgeHeatAction:
    unit_id: str
    bolster: str | None = None  # "reboot"


@dataclass
class ActivateUnit:
    unit_id: str


@dataclass
class EndActivation:
    pass


@dataclass
class Pass:
    pass


ACTION_TYPES = (
    MoveAction,
    RangedAttackAction,
    MeleeAttackAction,
    DisengageAction,
    PurgeHeatAction,
)
_ALL_TYPES = (*ACTION_TYPES, ActivateUnit, EndActivation, Pass)
_BY_NAME = {c.__name__: c for c in _ALL_TYPES}
_PATH_FIELDS = {"path"}


def is_action(x: object) -> bool:
    return isinstance(x, ACTION_TYPES)


def decision_to_dict(d: object) -> dict:
    out: dict = {"kind": type(d).__name__}
    for f in fields(d):  # type: ignore[arg-type]
        v = getattr(d, f.name)
        if f.name in _PATH_FIELDS and v is not None:
            v = [[h.q, h.r] for h in v]
        out[f.name] = v
    return out


def decision_from_dict(d: dict) -> object:
    d = dict(d)
    cls = _BY_NAME[d.pop("kind")]
    if "path" in d and d["path"] is not None:
        d["path"] = [Hex(int(p[0]), int(p[1])) for p in d["path"]]
    return cls(**d)
