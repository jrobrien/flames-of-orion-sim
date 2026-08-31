"""Pointy-top axial hex geometry. Pure, stdlib only.

Axial coords ``(q, r)``; implied cube ``s = -q - r``. ``DIRECTIONS`` is indexed
0..5 and doubles as a unit facing. Pixel helpers use ``size`` = circumradius
(centre to corner); the default ``size=1.0`` keeps distances in "hex" units for
the visibility sampler. See RULES.md section 0.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from heapq import heappop, heappush
from typing import NamedTuple

__all__ = [
    "DIRECTIONS",
    "Hex",
    "add",
    "corners",
    "distance",
    "from_offset_oddr",
    "from_pixel",
    "from_pixel_frac",
    "hex_round",
    "line",
    "line_variants",
    "neighbor",
    "neighbors",
    "range_hexes",
    "reachable",
    "ring",
    "scale",
    "spiral",
    "sub",
    "to_offset_oddr",
    "to_pixel",
]

_SQRT3 = math.sqrt(3.0)


class Hex(NamedTuple):
    q: int
    r: int

    @property
    def s(self) -> int:
        return -self.q - self.r


DIRECTIONS: tuple[Hex, ...] = (
    Hex(1, 0),
    Hex(1, -1),
    Hex(0, -1),
    Hex(-1, 0),
    Hex(-1, 1),
    Hex(0, 1),
)


def add(a: Hex, b: Hex) -> Hex:
    return Hex(a.q + b.q, a.r + b.r)


def sub(a: Hex, b: Hex) -> Hex:
    return Hex(a.q - b.q, a.r - b.r)


def scale(a: Hex, k: int) -> Hex:
    return Hex(a.q * k, a.r * k)


def neighbor(h: Hex, direction: int) -> Hex:
    return add(h, DIRECTIONS[direction % 6])


def neighbors(h: Hex) -> list[Hex]:
    return [add(h, d) for d in DIRECTIONS]


def distance(a: Hex, b: Hex) -> int:
    dq = a.q - b.q
    dr = a.r - b.r
    return (abs(dq) + abs(dq + dr) + abs(dr)) // 2


def hex_round(qf: float, rf: float) -> Hex:
    """Nearest hex to fractional axial coords, via cube rounding."""
    xf, zf = qf, rf
    yf = -xf - zf
    x, y, z = round(xf), round(yf), round(zf)
    dx, dy, dz = abs(x - xf), abs(y - yf), abs(z - zf)
    if dx > dy and dx > dz:
        x = -y - z
    elif dy > dz:
        y = -x - z
    else:
        z = -x - y
    return Hex(int(x), int(z))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def line(a: Hex, b: Hex, *, nudge: float = 1e-6) -> list[Hex]:
    """Hexes from ``a`` to ``b`` inclusive. ``nudge`` biases edge-straddling
    samples so the result is stable; flip its sign for the other variant."""
    n = distance(a, b)
    if n == 0:
        return [a]
    aq, ar = a.q + nudge, a.r + nudge
    bq, br = b.q + nudge, b.r + nudge
    return [hex_round(_lerp(aq, bq, i / n), _lerp(ar, br, i / n)) for i in range(n + 1)]


def line_variants(a: Hex, b: Hex, *, nudge: float = 1e-6) -> list[list[Hex]]:
    """Both nudge variants of :func:`line` - useful for "is *any* line clear"."""
    return [line(a, b, nudge=nudge), line(a, b, nudge=-nudge)]


def range_hexes(center: Hex, radius: int) -> list[Hex]:
    """All hexes within ``radius`` (inclusive). Count = 1 + 3*radius*(radius+1)."""
    out: list[Hex] = []
    for dq in range(-radius, radius + 1):
        lo = max(-radius, -dq - radius)
        hi = min(radius, -dq + radius)
        for dr in range(lo, hi + 1):
            out.append(Hex(center.q + dq, center.r + dr))
    return out


def ring(center: Hex, radius: int) -> list[Hex]:
    """Hexes at exactly ``radius`` (``radius <= 0`` returns ``[center]``)."""
    if radius <= 0:
        return [center]
    results: list[Hex] = []
    h = add(center, scale(DIRECTIONS[4], radius))
    for i in range(6):
        for _ in range(radius):
            results.append(h)
            h = neighbor(h, i)
    return results


def spiral(center: Hex, radius: int) -> list[Hex]:
    out = [center]
    for k in range(1, radius + 1):
        out.extend(ring(center, k))
    return out


def _as_pred(blocked: Callable[[Hex], bool] | set | frozenset | None) -> Callable[[Hex], bool]:
    if blocked is None:
        return lambda _h: False
    if isinstance(blocked, (set, frozenset)):
        return lambda h: h in blocked
    return blocked


def reachable(
    start: Hex,
    budget: int,
    *,
    blocked: Callable[[Hex], bool] | set | frozenset | None = None,
    step_cost: Callable[[Hex, Hex], int] | None = None,
) -> dict[Hex, int]:
    """Min movement cost from ``start`` to every hex reachable within ``budget``.

    Pure geometry: ``blocked`` hexes are impassable; ``start`` itself is never
    tested. Rules like "move through friendlies but don't end on them" are the
    caller's job (filter the returned dict).
    """
    is_blocked = _as_pred(blocked)
    cost_fn = step_cost or (lambda _a, _b: 1)
    best: dict[Hex, int] = {start: 0}
    frontier: list[tuple[int, Hex]] = [(0, start)]
    while frontier:
        c, h = heappop(frontier)
        if c > best.get(h, math.inf):
            continue
        for nb in neighbors(h):
            if is_blocked(nb):
                continue
            nc = c + cost_fn(h, nb)
            if nc <= budget and nc < best.get(nb, math.inf):
                best[nb] = nc
                heappush(frontier, (nc, nb))
    return best


def to_pixel(h: Hex, size: float = 1.0) -> tuple[float, float]:
    x = size * (_SQRT3 * h.q + _SQRT3 / 2.0 * h.r)
    y = size * (1.5 * h.r)
    return (x, y)


def from_pixel_frac(x: float, y: float, size: float = 1.0) -> tuple[float, float]:
    """Pixel -> fractional axial (q, r), no rounding."""
    return ((_SQRT3 / 3.0 * x - 1.0 / 3.0 * y) / size, (2.0 / 3.0 * y) / size)


def from_pixel(x: float, y: float, size: float = 1.0) -> Hex:
    q, r = from_pixel_frac(x, y, size)
    return hex_round(q, r)


def corners(h: Hex, size: float = 1.0) -> list[tuple[float, float]]:
    cx, cy = to_pixel(h, size)
    out: list[tuple[float, float]] = []
    for k in range(6):
        ang = math.radians(60 * k - 30)
        out.append((cx + size * math.cos(ang), cy + size * math.sin(ang)))
    return out


def from_offset_oddr(col: int, row: int) -> Hex:
    """odd-r pointy-top offset (col, row) -> axial. Used for rectangular maps."""
    q = col - (row - (row & 1)) // 2
    return Hex(q, row)


def to_offset_oddr(h: Hex) -> tuple[int, int]:
    """Axial -> odd-r pointy-top offset (col, row)."""
    col = h.q + (h.r - (h.r & 1)) // 2
    return (col, h.r)
