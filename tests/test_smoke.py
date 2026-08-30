"""Placeholder so CI has something to run before M1. Replace as real tests land."""

import tomllib
from pathlib import Path

import foosim

RULES_TOML = Path(__file__).resolve().parents[1] / "data" / "rules.toml"


def test_package_imports():
    assert foosim.__version__


def test_rules_toml_parses():
    with RULES_TOML.open("rb") as f:
        rules = tomllib.load(f)
    assert rules["meta"]["edition"] == "free-10.10"
    assert len(rules["ranged_weapons"]) == 8
    assert len(rules["melee_weapons"]) == 8
    assert len(rules["ammo"]) == 6
    assert len(rules["upgrades"]) == 20
    assert set(rules["catastrophic"]) == {str(n) for n in range(2, 13)}
    assert len(rules["call_sign"]["table_a"]) == 6
    assert all(len(row) == 6 for row in rules["call_sign"]["table_b"])
