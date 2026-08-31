"""Line of sight and cover on the hex board. Pure, stdlib only.

The tabletop rule is "any part of the model to any part of the target", eyeballed
over 3D terrain. Centre-to-centre hex LOS is too strict for how Flames of Orion
actually plays. This module offers pluggable models, tunable from
``data/rules.toml [visibility]``:

``multiray_2d`` (default)
    Sample several points across the attacker and target hexes. LOS holds if
    *any* sightline avoids ``blocking`` terrain. Cover applies if *some*
    sightline clips ``blocking``/``cover`` terrain or a third model (i.e. the
    target is partially obscured).

``strict_center``
    A single centre-to-centre line. Kept for comparison / debugging.

``center_25d``
    Centre line with 2.5D heights: a beam from the observer's eye to the top of
    the target, blocked when an intervening terrain column (ground elevation +
    structure height, via ``Board.column_height``) rises above it. Experimental;
    needs elevation data on maps (M2+).

``resolve.py`` calls :func:`line_of_sight` and never re-implements this. Weapons
that ignore LOS or cover just discard the relevant field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from foosim.engine import hexgrid
from foosim.engine.hexgrid import Hex

__all__ = [
    "Board",
    "DictBoard",
    "LosResult",
    "VisibilityConfig",
    "can_see",
    "line_of_sight",
]



@dataclass(frozen=True)
class VisibilityConfig:
    mode: str = "multiray_2d"
    eye_height: float = 1.0
    model_height: float = 1.0
    sample_corner_fraction: float = 0.85

    @classmethod
    def from_rules(cls, rules: dict) -> VisibilityConfig:
        v = rules.get("visibility", {}) if isinstance(rules, dict) else {}
        return cls(
            mode=v.get("mode", cls.mode),
            eye_height=float(v.get("eye_height", cls.eye_height)),
            model_height=float(v.get("model_height", cls.model_height)),
            sample_corner_fraction=float(
                v.get("sample_corner_fraction", cls.sample_corner_fraction)
            ),
        )


@dataclass(frozen=True)
class LosResult:
    los: bool
    cover: bool
    blocked_by: Hex | None = None
    cover_sources: tuple[Hex, ...] = ()


class Board(Protocol):
    def blocks_los(self, h: Hex) -> bool: ...
    def is_cover(self, h: Hex) -> bool: ...
    def has_model(self, h: Hex) -> bool: ...
    def column_height(self, h: Hex) -> float: ...


@dataclass
class DictBoard:
    """A trivial :class:`Board` for tests and simple maps. ``GameState`` will
    provide its own adapter later."""

    blocking: set[Hex] = field(default_factory=set)
    cover: set[Hex] = field(default_factory=set)
    models: set[Hex] = field(default_factory=set)
    heights: dict[Hex, float] = field(default_factory=dict)

    def blocks_los(self, h: Hex) -> bool:
        return h in self.blocking

    def is_cover(self, h: Hex) -> bool:
        return h in self.cover

    def has_model(self, h: Hex) -> bool:
        return h in self.models

    def column_height(self, h: Hex) -> float:
        return self.heights.get(h, 0.0)


def line_of_sight(
    board: Board,
    a: Hex,
    b: Hex,
    cfg: VisibilityConfig | None = None,
) -> LosResult:
    cfg = cfg or VisibilityConfig()
    if a == b:
        return LosResult(True, False)
    if cfg.mode == "strict_center":
        return _los_strict(board, a, b)
    if cfg.mode == "center_25d":
        return _los_25d(board, a, b, cfg)
    return _los_multiray(board, a, b, cfg)


def can_see(board: Board, a: Hex, b: Hex, cfg: VisibilityConfig | None = None) -> bool:
    return line_of_sight(board, a, b, cfg).los


# -- strict centre line -------------------------------------------------------


def _los_strict(board: Board, a: Hex, b: Hex) -> LosResult:
    interior = [h for h in hexgrid.line(a, b) if h != a and h != b]
    hard = [h for h in interior if board.blocks_los(h)]
    if hard:
        return LosResult(False, False, blocked_by=hard[0])
    soft = [h for h in interior if board.is_cover(h) or board.has_model(h)]
    return LosResult(True, bool(soft), cover_sources=tuple(soft))


# -- 2D multi-ray -----------------------------------------------------------


def _sample_points(h: Hex, frac: float) -> list[tuple[float, float]]:
    # centre + 3 alternating corners: 4 points, 16 ray-pairs per LOS check
    cx, cy = hexgrid.to_pixel(h, 1.0)
    pts = [(cx, cy)]
    for corner in hexgrid.corners(h, 1.0)[::2]:
        pts.append((cx + (corner[0] - cx) * frac, cy + (corner[1] - cy) * frac))
    return pts


_SUB = 4  # samples per hex of separation - dense enough not to skip a single hex


def _hexes_on_segment(p: tuple[float, float], q: tuple[float, float]) -> list[Hex]:
    """Hexes a pixel-space segment passes through, via axial cube interpolation
    (O(hex distance) rounds instead of a fine pixel walk)."""
    aq, ar = hexgrid.from_pixel_frac(p[0], p[1], 1.0)
    bq, br = hexgrid.from_pixel_frac(q[0], q[1], 1.0)
    hexdist = (abs(aq - bq) + abs(aq + ar - bq - br) + abs(ar - br)) / 2.0
    steps = max(2, int(hexdist * _SUB) + 1)
    out: list[Hex] = []
    prev: Hex | None = None
    inv = 1.0 / steps
    dq, dr = bq - aq, br - ar
    for i in range(steps + 1):
        t = i * inv
        h = hexgrid.hex_round(aq + dq * t, ar + dr * t)
        if h != prev:
            out.append(h)
            prev = h
    return out


def _los_multiray(board: Board, a: Hex, b: Hex, cfg: VisibilityConfig) -> LosResult:
    if hexgrid.distance(a, b) == 1:
        return LosResult(True, False)
    ends = {a, b}
    pa = _sample_points(a, cfg.sample_corner_fraction)
    pb = _sample_points(b, cfg.sample_corner_fraction)
    any_clear = False
    obscured = False
    cover_src: set[Hex] = set()
    blocked_example: Hex | None = None
    for p in pa:
        for q in pb:
            interior = [h for h in _hexes_on_segment(p, q) if h not in ends]
            hard = [h for h in interior if board.blocks_los(h)]
            if hard:
                blocked_example = blocked_example or hard[0]
                cover_src.update(hard)
                obscured = True
                continue
            any_clear = True
            soft = [h for h in interior if board.is_cover(h) or board.has_model(h)]
            if soft:
                obscured = True
                cover_src.update(soft)
    if not any_clear:
        centre_block = [
            h for h in hexgrid.line(a, b) if h not in ends and board.blocks_los(h)
        ]
        first = centre_block[0] if centre_block else blocked_example
        return LosResult(False, False, blocked_by=first)
    return LosResult(True, obscured, cover_sources=tuple(sorted(cover_src)))


# -- 2.5D centre beam -----------------------------------------------------


def _los_25d(board: Board, a: Hex, b: Hex, cfg: VisibilityConfig) -> LosResult:
    n = hexgrid.distance(a, b)
    if n == 0:
        return LosResult(True, False)
    z0 = board.column_height(a) + cfg.eye_height
    z1 = board.column_height(b) + cfg.model_height
    cover_src: list[Hex] = []
    for h in hexgrid.line(a, b):
        if h in (a, b):
            continue
        t = hexgrid.distance(a, h) / n
        beam = z0 + (z1 - z0) * t
        col = board.column_height(h)
        if col >= beam:
            return LosResult(False, False, blocked_by=h)
        has_obstacle = board.blocks_los(h) or board.is_cover(h) or board.has_model(h)
        if has_obstacle and col >= beam - cfg.model_height:
            cover_src.append(h)
    return LosResult(True, bool(cover_src), cover_sources=tuple(cover_src))
