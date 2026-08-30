import pytest

from foosim.engine.rules import Ruleset, load


def test_loads_default_and_hash_is_stable():
    a = load()
    b = load()
    assert a.content_hash == b.content_hash
    assert len(a.content_hash) == 12


def test_core_accessors():
    r = load()
    assert r.frame("medium")["combat_skill"] == 4
    assert r.frame("heavy")["armor"] == 5
    assert r.frame_for_roll(1) == "light"
    assert r.frame_for_roll(5) == "heavy"
    assert r.weapon("medium_weapon")["damage"] == "2"
    assert r.weapon_kind("close_combat_weapon") == "melee"
    assert r.weapon_kind("rail_weapon") == "ranged"
    assert r.ammo_spec("hellfire_rounds")["special"] == ["plus1_damage"]
    assert r.upgrade("armor_mk2")["effect"]["set_armor"] == 4
    assert r.catastrophic(12)["name"] == "Cockpit Fire"
    assert r.phase_order == ["initiative", "activation", "heat"]
    assert r.heat_check_table("check_default")[1] == 2
    assert r.heat_check_table("check_heat_sink")[3] == 0


def test_unknown_ids_raise():
    r = load()
    with pytest.raises(KeyError):
        r.weapon("nope")
    with pytest.raises(KeyError):
        r.upgrade("nope")


def test_with_overrides_is_isolated():
    r = load()
    base_lr = r.to_hit["long_range_inches"]
    r2 = r.with_overrides({"to_hit.long_range_inches": 8, "heat.second_action": 2})
    assert r2.to_hit["long_range_inches"] == 8
    assert r2.heat["second_action"] == 2
    assert r.to_hit["long_range_inches"] == base_lr  # original untouched
    assert r2.content_hash != r.content_hash


def test_with_overrides_creates_missing_path():
    r = load()
    r2 = r.with_overrides({"visibility.mode": "strict_center", "house_rules.brutal": True})
    assert r2.visibility["mode"] == "strict_center"
    assert r2.raw["house_rules"]["brutal"] is True


def test_validation_rejects_broken_ruleset():
    r = load()
    broken = {k: v for k, v in r.raw.items() if k != "catastrophic"}
    with pytest.raises(ValueError):
        Ruleset(broken)


def test_inches_to_hexes_uses_meta():
    r = load()
    assert r.inches_to_hexes(10) == 10  # default hex_per_inch == 1
