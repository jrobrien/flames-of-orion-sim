"""Per-mech / per-weapon extraction: totals reconcile with the game row, friendly fire
is excluded from damage-dealt, and the SQLite store round-trips."""

import json
import sqlite3

from foosim.ai.policy import GreedyPolicy
from foosim.engine.rules import load
from foosim.sim.analyze import run_games, run_one_full
from foosim.sim.generate import random_setup
from foosim.sim.store import RunMeta, Store, schema_doc, schema_sql

RULES = load()


def _game(seed):
    gs = random_setup(RULES, seed=seed)
    pols = {0: GreedyPolicy(RULES, seed * 2 + 1), 1: GreedyPolicy(RULES, seed * 2 + 2)}
    return run_one_full(gs, pols, RULES, seed)


def test_unit_damage_reconciles_with_game_row():
    for seed in range(6):
        r = _game(seed)
        dealt = sum(u.damage_weapon + u.damage_explosion + u.damage_self_destruct
                    + u.damage_other + u.friendly_damage for u in r.units)
        taken = sum(u.damage_taken for u in r.units)
        # ricochets are unattributed (no dealer), so dealt <= taken == game total
        assert taken == r.game.damage_dealt
        assert dealt <= taken
        assert len(r.units) == 8 and sum(u.leader for u in r.units) == 2
        wdmg = sum(w.damage for w in r.weapons)
        assert wdmg == sum(u.damage_weapon + u.damage_explosion + u.damage_self_destruct
                           + u.damage_other for u in r.units)
        for u in r.units:
            assert u.hits <= u.attacks and u.crits <= u.hits
            assert u.survived == int(u.out_round == 0)


def test_friendly_damage_is_not_counted_as_dealt():
    from foosim.engine.events import Event
    from foosim.engine.state import GameState

    seed = 3
    gs = random_setup(RULES, seed=seed)
    fake = [
        Event("damage", {"target": "A2", "amount": 3, "dealer": "A1", "source": "A1",
                            "weapon": "rail_weapon", "cause": "weapon", "friendly": True}),
        Event("damage", {"target": "B1", "amount": 2, "dealer": "A1", "source": "A1",
                            "weapon": "explosion", "cause": "explosion", "friendly": False}),
    ]
    from foosim.sim.gamestats import extract

    final: GameState = gs.copy()
    units, _ = extract(gs, final, fake, RULES, seed)
    a1 = next(u for u in units if u.unit_id == "A1")
    assert (a1.friendly_damage, a1.damage_explosion, a1.damage_weapon) == (3, 2, 0)


def test_store_round_trip_and_schema_docs(tmp_path):
    results = run_games(RULES, "skirmish", "greedy", "random", n=4, jobs=1)
    store = Store(tmp_path / "r.db")
    rid = store.add_run(RunMeta(setup="skirmish", bot0="greedy", bot1="random", games=4,
                                ruleset_hash=RULES.content_hash), results)
    store.close()
    db = sqlite3.connect(tmp_path / "r.db")
    assert db.execute("select count(*) from games where run_id=?", (rid,)).fetchone()[0] == 4
    assert db.execute("select count(*) from units").fetchone()[0] == sum(
        len(r.units) for r in results)
    ups = db.execute("select count(*) from unit_upgrades").fetchone()[0]
    assert ups == sum(len(json.loads(u.upgrades)) for r in results for u in r.units)
    doc = schema_doc()
    assert set(doc) == {"runs", "games", "units", "unit_weapons", "unit_upgrades"}
    assert all(c["doc"] for t in doc.values() for c in t)  # every column is documented
    assert "CREATE TABLE IF NOT EXISTS units" in schema_sql()
