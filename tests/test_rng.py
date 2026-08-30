import pytest

from foosim.engine.rng import Rng


def test_same_seed_same_stream():
    a = Rng.from_seed(2024)
    b = Rng.from_seed(2024)
    assert [a.d6() for _ in range(1000)] == [b.d6() for _ in range(1000)]


def test_serialization_resumes_identically():
    a = Rng.from_seed(7)
    [a.d6() for _ in range(50)]
    b = Rng.from_dict(a.to_dict())
    assert [a.d6() for _ in range(100)] == [b.d6() for _ in range(100)]


def test_fork_is_reproducible_and_diverges():
    a = Rng.from_seed(99)
    b = Rng.from_seed(99)
    fa = a.fork()
    fb = b.fork()
    assert [fa.d6() for _ in range(100)] == [fb.d6() for _ in range(100)]
    # the fork consumed one draw from the parent; parents still agree with each other
    assert [a.d6() for _ in range(100)] == [b.d6() for _ in range(100)]
    # child stream differs from parent's continuation
    assert a.fork().pool(20) != Rng.from_seed(99).pool(20)


def test_d6_distribution_roughly_uniform():
    r = Rng.from_seed(1)
    counts = [0] * 7
    for _ in range(60_000):
        counts[r.d6()] += 1
    for face in range(1, 7):
        assert 9_000 < counts[face] < 11_000, (face, counts)


def test_randint_small_span_unbiased():
    r = Rng.from_seed(5)
    counts = {1: 0, 2: 0, 3: 0}
    for _ in range(30_000):
        counts[r.randint(1, 3)] += 1
    for v in counts.values():
        assert 9_000 < v < 11_000, counts


def test_roll_specs():
    r = Rng.from_seed(3)
    assert r.roll("4") == 4
    assert r.roll(4) == 4
    for _ in range(500):
        assert 2 <= r.roll("2d6") <= 12
        assert 1 <= r.roll("d3") <= 3
        assert 1 <= r.roll("1d2") <= 2
        assert 3 <= r.roll("3d3") <= 9
    for bad in ("", "d", "2d", "x2d6", "2d6+1", "-1"):
        with pytest.raises(ValueError):
            r.roll(bad)


def test_d66_shape():
    r = Rng.from_seed(11)
    for _ in range(500):
        v = r.d66()
        tens, ones = divmod(v, 10)
        assert 1 <= tens <= 6 and 1 <= ones <= 6


def test_shuffle_is_permutation_and_deterministic():
    a = list(range(20))
    b = list(range(20))
    Rng.from_seed(42).shuffle(a)
    Rng.from_seed(42).shuffle(b)
    assert a == b
    assert sorted(a) == list(range(20))
    assert a != list(range(20))


def test_cross_language_golden_vector():
    """If this changes, every downstream replay and any language port breaks.
    Regenerate deliberately, never casually."""
    r = Rng.from_seed(0x0123456789ABCDEF)
    assert [r.d6() for _ in range(12)] == GOLDEN_D6


GOLDEN_D6 = [4, 6, 3, 3, 3, 5, 6, 4, 6, 4, 6, 1]
