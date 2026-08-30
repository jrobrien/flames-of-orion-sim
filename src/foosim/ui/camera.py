"""2D pan/zoom camera over the hex grid. Pure - no imgui.

Works in a local pixel space whose origin is the map region's top-left; the imgui
layer adds the region origin before drawing. ``scale`` is pixels per hex unit
(the hexgrid ``size``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from foosim.engine import hexgrid
from foosim.engine.hexgrid import Hex

__all__ = ["Camera"]


@dataclass
class Camera:
    scale: float = 26.0
    ox: float = 0.0
    oy: float = 0.0

    def world_to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        return (wx * self.scale + self.ox, wy * self.scale + self.oy)

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return ((sx - self.ox) / self.scale, (sy - self.oy) / self.scale)

    def hex_to_screen(self, h: Hex) -> tuple[float, float]:
        wx, wy = hexgrid.to_pixel(h, 1.0)
        return self.world_to_screen(wx, wy)

    def screen_to_hex(self, sx: float, sy: float) -> Hex:
        wx, wy = self.screen_to_world(sx, sy)
        return hexgrid.from_pixel(wx, wy, 1.0)

    def hex_corners_screen(self, h: Hex) -> list[tuple[float, float]]:
        return [self.world_to_screen(cx, cy) for cx, cy in hexgrid.corners(h, 1.0)]

    def zoom_at(
        self, sx: float, sy: float, factor: float, *, lo: float = 4.0, hi: float = 120.0
    ) -> None:
        """Scale by ``factor`` while keeping the world point under (sx, sy) fixed."""
        wx, wy = self.screen_to_world(sx, sy)
        self.scale = max(lo, min(hi, self.scale * factor))
        self.ox = sx - wx * self.scale
        self.oy = sy - wy * self.scale

    def pan(self, dx: float, dy: float) -> None:
        self.ox += dx
        self.oy += dy

    def fit(self, cells: Iterable[Hex], view_w: float, view_h: float, *, pad: float = 0.12) -> None:
        pts = [hexgrid.to_pixel(h, 1.0) for h in cells]
        if not pts:
            return
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        minx, maxx = min(xs) - 1.0, max(xs) + 1.0
        miny, maxy = min(ys) - 1.0, max(ys) + 1.0
        bw = max(maxx - minx, 1e-6)
        bh = max(maxy - miny, 1e-6)
        self.scale = min(view_w / bw, view_h / bh) * (1.0 - pad)
        cx = (minx + maxx) / 2.0
        cy = (miny + maxy) / 2.0
        self.ox = view_w / 2.0 - cx * self.scale
        self.oy = view_h / 2.0 - cy * self.scale
