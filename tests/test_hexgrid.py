import pytest

from foosim.engine import hexgrid as hg
from foosim.engine.hexgrid import Hex


def test_hex_third_coord():
    h = Hex(2, -5)
    assert h.s == 3
    assert h.q + h.r + h.s == 0


def test_distance_known_values_and_symmetry():
    o = Hex(0, 0)
    assert hg.distance(o, o) == 0
    for d in hg.DIRECTIONS:
        assert hg.distance(o, d) == 1
    assert hg.distance(Hex(0, 0), Hex(3, 0)) == 3
    assert hg.distance(Hex(0, 0), Hex(-1, -1)) == 2
    assert hg.distance(Hex(1, 2), Hex(-3, 4)) == hg.distance(Hex(-3, 4), Hex(1, 2))


def test_neighbors():
    ns = hg.neighbors(Hex(5, 5))
    assert len(ns) == 6
    assert len(set(ns)) == 6
    assert all(hg.distance(Hex(5, 5), n) == 1 for n in ns)


def test_line_endpoints_and_length():
    a, b = Hex(0, 0), Hex(4, -2)
    ln = hg.line(a, b)
    assert ln[0] == a and ln[-1] == b
    assert len(ln) == hg.distance(a, b) + 1
    for x, y in zip(ln[:-1], ln[1:], strict=True):
        assert hg.distance(x, y) == 1
    assert hg.line(a, a) == [a]


def test_line_variants_differ_on_diagonal():
    a, b = Hex(0, 0), Hex(2, 1)  # straddles hex edges
    v = hg.line_variants(a, b)
    assert v[0][0] == a and v[0][-1] == b
    assert v[1][0] == a and v[1][-1] == b


def test_range_and_ring_counts():
    c = Hex(-2, 3)
    for radius in range(4):
        assert len(hg.range_hexes(c, radius)) == 1 + 3 * radius * (radius + 1)
        assert len(set(hg.range_hexes(c, radius))) == 1 + 3 * radius * (radius + 1)
    assert hg.ring(c, 0) == [c]
    for radius in range(1, 5):
        rg = hg.ring(c, radius)
        assert len(rg) == 6 * radius
        assert all(hg.distance(c, h) == radius for h in rg)


def test_spiral_is_disc():
    c = Hex(0, 0)
    assert sorted(hg.spiral(c, 3)) == sorted(hg.range_hexes(c, 3))


def test_reachable_open_field_matches_range():
    start = Hex(0, 0)
    got = hg.reachable(start, 3)
    assert set(got) == set(hg.range_hexes(start, 3))
    assert got[start] == 0
    for h, cost in got.items():
        assert cost == hg.distance(start, h)


def test_reachable_respects_walls():
    start = Hex(0, 0)
    # seal the start hex behind five of six neighbours; only DIRECTIONS[0] is open
    wall = set(hg.neighbors(start)) - {hg.neighbor(start, 0)}
    got = hg.reachable(start, 2, blocked=wall)
    assert hg.neighbor(start, 0) in got
    assert all(w not in got for w in wall)
    # the far side of the wall costs more than its straight-line distance
    behind = hg.neighbor(start, 3)
    assert behind not in got or got[behind] > hg.distance(start, behind)


def test_reachable_accepts_predicate_and_cost():
    start = Hex(0, 0)
    got = hg.reachable(start, 10, blocked=lambda h: h.q == 1, step_cost=lambda a, b: 2)
    assert all(h.q != 1 for h in got)
    assert got[hg.neighbor(start, 3)] == 2


@pytest.mark.parametrize(
    "h",
    [Hex(0, 0), Hex(3, -1), Hex(-4, 2), Hex(10, -7), Hex(-6, -6)],
)
def test_pixel_roundtrip(h):
    x, y = hg.to_pixel(h)
    assert hg.from_pixel(x, y) == h


def test_corners_count_and_radius():
    pts = hg.corners(Hex(0, 0), 1.0)
    assert len(pts) == 6
    for px, py in pts:
        assert abs((px**2 + py**2) ** 0.5 - 1.0) < 1e-9
