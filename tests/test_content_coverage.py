"""Every weapon/ammo/upgrade/catastrophic hook in rules.toml is classified in
engine.effects (HANDLED or DEFERRED). A new unclassified token fails the suite.
"""

from foosim.engine.effects import (
    DEFERRED_SPECIALS,
    DEFERRED_UPGRADE_EFFECTS,
    HANDLED_SPECIALS,
    HANDLED_UPGRADE_EFFECTS,
)
from foosim.engine.rules import load

RULES = load()


def _all_specials():
    tokens = set()
    for key in ("ranged_weapons", "melee_weapons", "ammo", "upgrades"):
        for entry in RULES.raw.get(key, []):
            tokens.update(entry.get("special", []))
    return tokens


def test_every_special_token_is_handled_or_deferred():
    unknown = _all_specials() - HANDLED_SPECIALS - DEFERRED_SPECIALS
    assert not unknown, f"unclassified special tokens: {sorted(unknown)}"


def test_handled_and_deferred_do_not_overlap():
    assert not (HANDLED_SPECIALS & DEFERRED_SPECIALS)
    assert not (HANDLED_UPGRADE_EFFECTS & DEFERRED_UPGRADE_EFFECTS)


def test_every_upgrade_effect_key_is_handled_or_deferred():
    keys = set()
    for up in RULES.raw["upgrades"]:
        keys.update(up.get("effect", {}))
    unknown = keys - HANDLED_UPGRADE_EFFECTS - DEFERRED_UPGRADE_EFFECTS
    assert not unknown, f"unclassified upgrade effect keys: {sorted(unknown)}"


def test_catastrophic_effect_tokens_all_parse():
    from foosim.engine import resolve
    from foosim.engine.rng import Rng
    from foosim.sim.setups import skirmish_2v2

    gs = skirmish_2v2(RULES, seed=1)
    victim = gs.units["B1"]
    for roll in range(2, 13):
        cat = RULES.catastrophic(roll)
        ev: list = []
        resolve._apply_catastrophic(gs, victim, cat, RULES, Rng.from_seed(roll), ev)
        assert not any(e.kind == "unhandled_effect" for e in ev), (roll, cat)
