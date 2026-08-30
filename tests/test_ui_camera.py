import pytest

from foosim.engine.hexgrid import Hex
from foosim.engine.rules import load
from foosim.sim.setups import skirmish_2v2
from foosim.ui.camera import Camera


@pytest.mark.parametrize(
    "cam",
    [Camera(), Camera(scale=12.0, ox=40.0, oy=-15.0), Camera(scale=55.0, ox=-200.0, oy=300.0)],
)
@pytest.mark.parametrize("h", [Hex(0, 0), Hex(3, -2), Hex(-4, 5), Hex(9, 1), Hex(-7, -7)])
def test_screen_hex_roundtrip(cam, h):
    sx, sy = cam.hex_to_screen(h)
    assert cam.screen_to_hex(sx, sy) == h


def test_fit_places_every_cell_inside_the_viewport():
    cells = skirmish_2v2(load(), seed=1).mapspec.cells()
    cam = Camera()
    w, hgt = 800.0, 600.0
    cam.fit(cells, w, hgt)
    for c in cells:
        sx, sy = cam.hex_to_screen(c)
        assert -1.0 <= sx <= w + 1.0
        assert -1.0 <= sy <= hgt + 1.0


def test_zoom_at_keeps_the_cursor_world_point_fixed():
    cam = Camera(scale=20.0, ox=10.0, oy=5.0)
    px, py = 123.0, 77.0
    before = cam.screen_to_world(px, py)
    cam.zoom_at(px, py, 1.5)
    after = cam.screen_to_world(px, py)
    assert abs(before[0] - after[0]) < 1e-6
    assert abs(before[1] - after[1]) < 1e-6
    assert cam.scale == pytest.approx(30.0)


def test_zoom_clamps_to_bounds():
    cam = Camera(scale=5.0)
    cam.zoom_at(0.0, 0.0, 0.001)
    assert cam.scale >= 4.0
    cam.zoom_at(0.0, 0.0, 1000.0)
    assert cam.scale <= 120.0


def test_pan_translates_offset():
    cam = Camera(ox=0.0, oy=0.0)
    cam.pan(15.0, -7.0)
    assert (cam.ox, cam.oy) == (15.0, -7.0)
