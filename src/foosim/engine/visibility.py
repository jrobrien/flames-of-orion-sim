"""Line of sight and cover on the hex board. Pure, stdlib only.

The tabletop rule is "any part of the model to any part of the target", eyeballed
over 3D terrain. Centre-to-centre hex LOS is too strict for how Flames of Orion
actually plays. This module offers pluggable models, tunable from
``data/rules.toml [visibility]``:

``multiray_2d`` (default, but 2.5D)
    Sample several points across the attacker and target hexes and trace every
    sightline as a 3D beam from the observer's eye to the target. A ray is
    blocked when an intervening column - ``Board.column_height`` = ground
    elevation + opaque structure height (a ``blocking`` building, or a bare
    hill) - rises to or above the beam. LOS holds if *any* ray gets through;
    cover applies if *some* ray grazes an obstacle (a building top near the
    beam, low ``cover`` terrain, or a third model). So a mech on a tower or hill
    sees over walls that block a mech on the ground.

``strict_center``
    A single centre-to-centre line, no heights. Kept for comparison / debugging.

``center_25d``
    Like ``multiray_2d`` but only the centre line - the crude version.

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


_GRAZE = 0.01
_WALL_H = 2.0  # a bare 'blocking' hex (no explicit height) is a full-height wall


def _ray_hits(board: Board, interior: list[Hex], a: Hex, b: Hex, eye_a: float,
              eye_b: float, n_total: int, model_h: float):
    """-> (hard_block Hex | None, grazed [Hex])."""
    grazed: list[Hex] = []
    for h in interior:
        frac = hexgrid.distance(a, h) / n_total
        beam = eye_a + (eye_b - eye_a) * frac
        opaque = board.blocks_los(h)
        top = board.column_height(h)
        if opaque and top < _GRAZE:
            top = _WALL_H
        if opaque:
            if top >= beam - _GRAZE:
                return h, grazed
        elif top >= beam + _GRAZE:  # a bare hill you truly can't see over
            return h, grazed
        if (opaque or board.is_cover(h) or board.has_model(h)) and top >= beam - model_h:
            grazed.append(h)
    return None, grazed


def _los_multiray(board: Board, a: Hex, b: Hex, cfg: VisibilityConfig) -> LosResult:
    if hexgrid.distance(a, b) <= 1:
        return LosResult(True, False)
    ends = {a, b}
    n_total = hexgrid.distance(a, b)
    eye_a = board.column_height(a) + cfg.eye_height
    eye_b = board.column_height(b) + cfg.model_height  # can see any part of the target
    any_clear = False
    obscured = False
    cover_src: set[Hex] = set()
    blocked_example: Hex | None = None
    for p in _sample_points(a, cfg.sample_corner_fraction):
        for q in _sample_points(b, cfg.sample_corner_fraction):
            interior = [h for h in _hexes_on_segment(p, q) if h not in ends]
            hard, grazed = _ray_hits(board, interior, a, b, eye_a, eye_b, n_total,
                                     cfg.model_height)
            if hard is not None:
                blocked_example = blocked_example or hard
                cover_src.add(hard)
                obscured = True
                continue
            any_clear = True
            if grazed:
                obscured = True
                cover_src.update(grazed)
    if not any_clear:
        centre = [h for h in hexgrid.line(a, b) if h not in ends]
        c_hard, _ = _ray_hits(board, centre, a, b, eye_a, eye_b, n_total, cfg.model_height)
        return LosResult(False, False, blocked_by=c_hard or blocked_example)
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
