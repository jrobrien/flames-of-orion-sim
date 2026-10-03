"""The help system must describe everything that exists (so it cannot drift), and the
CLI subcommands must behave for both humans and agents."""

import json
import sqlite3

import pytest

from foosim.sim import analyze, catalog
from foosim.sim.analyze import _POLICIES, _SETUPS, _run_parser, main


def test_every_bot_setup_and_report_is_described():
    assert set(catalog.BOTS) == set(_POLICIES)
    assert set(catalog.SETUPS) == set(_SETUPS)
    for table in (catalog.BOTS, catalog.SETUPS, catalog.REPORTS):
        for name, e in table.items():
            assert e["summary"] and e["description"], name
    from foosim.sim.reports import REPORT_FUNCS

    assert set(catalog.REPORTS) == set(REPORT_FUNCS)


def test_every_run_flag_has_help_text():
    for a in _run_parser()._actions:
        assert a.help, a.option_strings


def test_squad_options_listed_for_random_setups_exist_as_flags():
    flags = {f for a in _run_parser()._actions for f in a.option_strings}
    for s in catalog.SETUPS.values():
        assert set(s["options"]) <= flags


def test_overview_and_unknown_command(capsys):
    main([])
    out = capsys.readouterr().out
    assert "greedy" in out and "report weapons" in out
    with pytest.raises(SystemExit) as e:
        main(["lst"])
    assert e.value.code == 2
    assert "Did you mean 'list'" in capsys.readouterr().err


def test_bad_bot_suggests_closest(capsys):
    with pytest.raises(SystemExit) as e:
        main(["run", "--matchup", "greedy-vs-rando", "--games", "1"])
    assert e.value.code == 2
    assert "Did you mean 'random'" in capsys.readouterr().err


def test_list_describe_manifest_json(capsys):
    main(["list", "gear", "--json"])
    gear = json.loads(capsys.readouterr().out)
    sd = next(g for g in gear if g["id"] == "self_destruct")
    assert sd["simulated"] is True and sd["cost"] == 10000
    assert any(g["simulated"] is False for g in gear)

    main(["describe", "greedy", "--json"])
    assert json.loads(capsys.readouterr().out)["kind"] == "bot"

    main(["manifest"])
    m = json.loads(capsys.readouterr().out)
    assert {"commands", "run_flags", "bots", "setups", "schema", "gear"} <= set(m)
    assert any("--db" in f["flags"] for f in m["run_flags"])


def test_legacy_flat_invocation_still_runs(capsys):
    main(["--games", "2", "--setup", "skirmish", "-j", "1"])
    assert "games                2" in capsys.readouterr().out


def test_run_db_and_reports_end_to_end(tmp_path, capsys):
    db = tmp_path / "r.db"
    main(["run", "--games", "6", "--db", str(db), "--label", "t", "-j", "2",
          "--squad-seed-0", "5", "--mirror"])
    assert "stored run 1" in capsys.readouterr().out
    con = sqlite3.connect(db)
    row = con.execute("select setup_opts, label, bot0 from runs").fetchone()
    assert json.loads(row[0])["squad_seed_0"] == 5 and row[1:] == ("t", "greedy")
    for name in ("weapons", "frames", "upgrades"):
        main(["report", name, "--db", str(db), "--json"])
        out = json.loads(capsys.readouterr().out)
        assert out["runs"] == [1] and "rows" in out
    main(["report", "weapons", "--db", str(db)])
    assert "damage_per_mech_game" in capsys.readouterr().out
    assert analyze  # module import sanity
