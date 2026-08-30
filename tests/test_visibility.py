from foosim.engine.hexgrid import Hex
from foosim.engine.visibility import (
    DictBoard,
    VisibilityConfig,
    line_of_sight,
)

STRICT = VisibilityConfig(mode="strict_center")
MULTI = VisibilityConfig(mode="multiray_2d")
D25 = VisibilityConfig(mode="center_25d")

A = Hex(0, 0)
B = Hex(0, 6)  # six hexes away, straight down the r axis
MID = Hex(0, 3)


def test_adjacent_always_visible_no_cover():
    board = DictBoard(blocking={Hex(0, 1)})
    for cfg in (STRICT, MULTI, D25):
        res = line_of_sight(board, A, Hex(1, 0), cfg)
        assert res.los and not res.cover


def test_open_ground_clear_no_cover():
    board = DictBoard()
    for cfg in (STRICT, MULTI, D25):
        res = line_of_sight(board, A, B, cfg)
        assert res.los and not res.cover


def test_wall_on_centre_line_blocks_all_modes():
    board = DictBoard(blocking={MID})
    for cfg in (STRICT, MULTI):
        res = line_of_sight(board, A, B, cfg)
        assert not res.los
        assert res.blocked_by == MID


def test_single_offset_blocker_is_cover_not_block_for_multiray():
    """A blocker one hex off the centre line: strict LOS still passes (it never
    touches the hex), multi-ray keeps LOS but reports cover because corner rays
    clip it. This is the whole reason multiray_2d exists."""
    off = Hex(1, 3)
    board = DictBoard(blocking={off})
    strict = line_of_sight(board, A, B, STRICT)
    assert strict.los and not strict.cover

    multi = line_of_sight(board, A, B, MULTI)
    assert multi.los and multi.cover
    assert off in multi.cover_sources


def test_wall_spanning_corridor_blocks_multiray():
    board = DictBoard(blocking={Hex(-1, 3), Hex(0, 3), Hex(1, 3)})
    res = line_of_sight(board, A, B, MULTI)
    assert not res.los


def test_cover_terrain_grants_cover_but_not_block():
    board = DictBoard(cover={MID})
    for cfg in (STRICT, MULTI):
        res = line_of_sight(board, A, B, cfg)
        assert res.los and res.cover
        assert MID in res.cover_sources


def test_intervening_model_grants_cover():
    board = DictBoard(models={MID})
    for cfg in (STRICT, MULTI):
        res = line_of_sight(board, A, B, cfg)
        assert res.los and res.cover


def test_25d_tall_column_blocks_but_elevated_observer_sees_over():
    low = DictBoard(heights={MID: 5.0}, blocking={MID})
    assert not line_of_sight(low, A, B, D25).los

    # observer standing on a tall structure at A looks over the same column
    elevated = DictBoard(heights={A: 10.0, MID: 5.0}, blocking={MID})
    res = line_of_sight(elevated, A, B, D25)
    assert res.los


def test_from_rules_reads_visibility_table():
    cfg = VisibilityConfig.from_rules({"visibility": {"mode": "strict_center", "eye_height": 2.0}})
    assert cfg.mode == "strict_center"
    assert cfg.eye_height == 2.0
    assert VisibilityConfig.from_rules({}).mode == "multiray_2d"
