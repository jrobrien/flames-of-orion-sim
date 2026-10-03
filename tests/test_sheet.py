from foosim.engine.rules import load
from foosim.sim.sheet import PER_PAGE, render_sheet


def test_sheet_has_four_blocks_per_page_and_is_deterministic():
    rules = load()
    html = render_sheet(rules, seed=3, pages=2)
    assert html.count('class="unit"') == 2 * PER_PAGE
    assert html.count('class="page"') == 2
    assert html == render_sheet(rules, seed=3, pages=2)
    assert html != render_sheet(rules, seed=4, pages=2)


def test_squad_is_heavy_leader_two_mediums_one_light_with_one_valid_perk():
    from foosim.engine.rng import Rng
    from foosim.sim.generate import SQUAD_FRAMES as SQUAD
    from foosim.sim.generate import generate_mech, pick_perk

    assert list(SQUAD) == ["heavy", "medium", "medium", "light"]
    rules = load()
    html = render_sheet(rules, seed=3)
    assert html.count("Squad leader") == 1 and html.count("Perk &ndash;") == 1
    for seed in range(200):
        rng = Rng.from_seed(seed)
        u = generate_mech(rules, rng, id="x", side=0, frame="heavy", supported_only=False)
        kinds = {w.kind for w in u.weapons}
        perk = pick_perk(rules, rng, u)
        assert perk.get("requires", "any") in kinds | {"any"}


def test_every_platform_has_a_cost():
    rules = load()
    for key in ("ranged_weapons", "melee_weapons", "ammo", "upgrades"):
        assert all(x["cost"] > 0 for x in rules.raw[key])


def test_blank_sheet_has_long_trackers_and_no_stats():
    html = render_sheet(load(), seed=1, blank=True)
    assert html.count('class="unit"') == PER_PAGE
    assert html.count('class="o"') == PER_PAGE * 30  # 20 heat + 10 HP circles per block
    assert "Squad leader" not in html
