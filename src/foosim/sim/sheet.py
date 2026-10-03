"""Printable random-mech unit sheets (HTML, one four-mech squad per page).

  foosim-sheet --seed 7 --pages 2 --out mechs.html
  foosim-sheet --blank --pages 3 --out blank.html   # empty sheets to fill in by hand

Each page is one squad: a Heavy squad leader (with one Experience perk) on top, two
Mediums and a Light below. Mechs come from ``generate_mech`` (same Black Market
tables as ``foosim-gen-unit``, whole table by default) and are laid out like the
official simple unit sheet: call sign, S / CS / AR / HL, a Platforms list with
costs, a total-cost box, and Heat / HP trackers drawn as little circles to tick off
with a pen. Open the file in a browser and print (Letter portrait, margins already set;
turn "background graphics" off, it is pure black on white).
"""

from __future__ import annotations

import argparse
from html import escape
from pathlib import Path

from foosim.engine.rng import Rng
from foosim.engine.rules import Ruleset
from foosim.engine.rules import load as load_rules
from foosim.engine.state import Unit
from foosim.sim.generate import SQUAD_FRAMES, generate_squad

__all__ = ["main", "render_sheet"]

PER_PAGE = len(SQUAD_FRAMES)
MIN_ROWS = 5  # platform rows drawn even when a mech has fewer entries

# Short table text for the SPECIAL column, by weapon / ammo / upgrade id. Anything
# missing falls back to a blank cell, so new content never breaks the sheet.
_WEAPON_TEXT = {
    "flame_thrower": 'Range 10"; target +1d2 heat on hit; no ammo',
    "heavy_weapon": "Half speed if fired (2 PF)",
    "rail_weapon": "Line attack; hits friendlies; +1 heat to self",
    "ai_missile_system": 'Range 20"; ignores LOS, cover, long-range penalty',
    "long_range_systems": "Armor penetration; no long-range penalty",
    "large_missile_battery": 'Splash 2"',
    "cable_whip": 'Reach 3"',
    "lance": "+2 dmg and AP if moved",
    "power_weapon": "Armor penetration; on a 1 loses AP",
    "electric_field": 'Hits all within 2"; push 1"',
    "piston_gauntlet": 'Push target 1" on hit',
    "energy_sword": "Crit on 5+; on a 1 becomes 1 dmg",
}
_AMMO_TEXT = {
    "flechette_rounds": "armor penetration",
    "hellfire_rounds": "+1 dmg",
    "emf_rounds": "target -2 S until its next activation",
    "concussive_rounds": 'push 2"; 1 collision dmg',
    "rapid_fire_rounds": "extra attack on a hit roll of 6",
    "tracer_rounds": "both positions compromised",
}
_UPGRADE_TEXT = {
    "armor_mk1": "AR 5+",
    "armor_mk2": "AR 4+",
    "reactive_armor": "Ignore the first damage taken",
    "vtol": "Ignores terrain when moving",
    "thrusters": "+1 S",
    "heat_sink": "Uses the Heat Sink heat-check table",
    "sensor_array": "Crits do +1 damage",
    "heavy_plating": "+1 HP",
    "core_stabilizers": "+2 HL",
    "extra_platforms": "+1 PF (takes no slot)",
    "self_destruct": "Action: self-destruct at heat 7+",
    "camouflage": "Action: active camo; enemy ranged CS penalty",
    "nuclear_core": "Explodes as 10 heat",
    "targeting_system": "+1 CS",
    "up_link": "Action: Up-Link (position compromised)",
    "long_range_targeting": "Ignores long-range penalty",
    "defense_array": 'Repel within 1" on 4+',
    "thermal_imaging": "+1 CS vs targets at heat 5+",
    "counter_missiles": "Negates ranged crit bonus damage",
    "virus_program": "Action: infect (once per game)",
}


# Effect keys that are baked into a unit's printed stats -> the stat they change.
_EFFECT_STAT = {
    "set_armor": "AR", "speed_delta": "S", "cs_delta": "CS", "heat_limit_delta": "HL",
    "hull_points_delta": "HP", "platform_slots_delta": "PF",
}
# Effect keys that change a stat only in some situations; never baked into the printout.
_CONDITIONAL_STAT = {
    "cs_delta_vs_hot_target": "CS", "cs_delta_melee": "CS", "cs_delta_ranged": "CS",
}
# One footnote symbol per stat, so a tag in a description points at its stat box.
_MARK = {"S": "*", "CS": "\u2020", "AR": "\u2021", "HL": "\u00a7", "HP": "\u00b6", "PF": "#"}


def _stats_changed(effect: dict) -> list[str]:
    return [stat for key, stat in _EFFECT_STAT.items() if key in effect]


def _stats_conditional(effect: dict) -> list[str]:
    return [stat for key, stat in _CONDITIONAL_STAT.items() if key in effect]


def _applied(text: str, effect: dict) -> str:
    """Tag a description with the stats it touches: ``already in`` for printed-in
    changes, ``can modify`` for situational ones that are not."""
    tags = [f"already in {st}{_MARK[st]}" for st in _stats_changed(effect)]
    tags += [f"can modify {st}{_MARK[st]}, not included" for st in _stats_conditional(effect)]
    if not tags:
        return text
    tag = f"({'; '.join(tags)})"
    return f"{text} {tag}" if text else tag


def _money(n: int) -> str:
    return f"{n:,}$"


def _rows(rules: Ruleset, u: Unit) -> list[tuple[str, str, str, str]]:
    """(name, dmg, special, cost) per Platforms row: weapons first, then upgrades.
    Ammo is bought separately, so its price is added to its weapon's row."""
    out: list[tuple[str, str, str, str]] = []
    for w in u.weapons:
        spec = rules.weapon(w.weapon_id)
        tag = "(M) " if w.kind == "melee" else ""
        special = _WEAPON_TEXT.get(w.weapon_id, "")
        cost = int(spec.get("cost", 0))
        if w.ammo_id:
            ammo = rules.ammo_spec(w.ammo_id)
            note = f"{ammo['name']}: {_AMMO_TEXT.get(w.ammo_id, '')}".rstrip(": ")
            special = f"{special}; {note}" if special else note
            cost += int(ammo.get("cost", 0))
        out.append((tag + spec["name"], str(spec.get("damage", "")), special, _money(cost)))
    for uid in u.upgrades:
        up = rules.upgrade(uid)
        text = _applied(_UPGRADE_TEXT.get(uid, ""), up.get("effect", {}))
        out.append((up["name"], "", text, _money(int(up.get("cost", 0)))))
    return out


def _total_cost(rules: Ruleset, u: Unit) -> int:
    """Mech price plus every platform and ammo (modded frames cost nothing extra)."""
    total = int(rules.raw["game"]["mech_cost"])
    for w in u.weapons:
        total += int(rules.weapon(w.weapon_id).get("cost", 0))
        if w.ammo_id:
            total += int(rules.ammo_spec(w.ammo_id).get("cost", 0))
    return total + sum(int(rules.upgrade(uid).get("cost", 0)) for uid in u.upgrades)


def _circles(n: int, label: bool = False) -> str:
    cells = "".join(f'<i class="o">{i + 1 if label else ""}</i>' for i in range(n))
    return f'<div class="circles">{cells}</div>'


def _block(rules: Ruleset, u: Unit, n: int, perk: dict | None = None) -> str:
    frame = u.profile.split(".")[-1].title()
    rows = _rows(rules, u)
    rows += [("", "", "", "")] * max(0, MIN_ROWS - len(rows))
    plat = "".join(
        f"<tr><td class='w'>{escape(a)}</td><td class='d'>{escape(b)}</td>"
        f"<td class='s'>{escape(c)}</td><td class='c'>{escape(k)}</td></tr>"
        for a, b, c, k in rows
    )
    effects = [rules.upgrade(uid).get("effect", {}) for uid in u.upgrades]
    effects += [perk.get("effect", {})] if perk else []
    starred = {st for e in effects for st in _stats_changed(e) + _stats_conditional(e)}
    star = {k: _MARK[k] if k in starred else "" for k in _MARK}
    leader = '<span class="lead">Squad leader</span>' if perk else ""
    notes = (
        f"<b>Perk &ndash; {escape(perk['name'])}:</b> "
        f"{escape(_applied(perk['text'], perk.get('effect', {})))} (5 XP)"
        if perk else ""
    )
    return f"""
<section class="unit">
  <header><b>{n:02d}</b> &ndash; <span class="sign">{escape(u.name)}</span>{leader}
    <span class="frame">{frame} frame &middot; {u.platforms} PF{star['PF']}</span></header>
  <div class="body">
    <div class="left">
      <div class="stats">
        <div><span>S</span><b>{u.speed}{star['S']}</b></div>
        <div><span>CS</span><b>{u.cs}+{star['CS']}</b></div>
        <div><span>AR</span><b>{u.ar}+{star['AR']}</b></div>
        <div><span>HL</span><b>{u.heat_limit}{star['HL']}</b></div>
      </div>
      <div class="trk"><span>Heat tracker</span>{_circles(u.heat_limit, label=True)}</div>
      <div class="trk"><span>HP tracker{star['HP']}</span>{_circles(u.hp_max)}</div>
    </div>
    <div class="platwrap"><table class="plat">
      <thead><tr><th class="w">Platforms</th><th class="d">Dmg</th>
        <th class="s">Special</th><th class="c">Cost</th></tr></thead>
      <tbody>{plat}</tbody>
    </table></div>
  </div>
  <div class="foot2">
    <div class="notes"><span>Notes</span> {notes}</div>
    <div class="total"><span>Total cost</span> <b>{_money(_total_cost(rules, u))}</b></div>
  </div>
</section>"""


_CSS = """
@page { size: __PAPER__ portrait; margin: 0.3in; }
* { box-sizing: border-box; }
body { margin: 0; font: 10px/1.2 "DejaVu Sans Condensed", "Arial Narrow", Arial, sans-serif;
       color: #000; background: #fff; }
.page { height: 10.2in; width: 7.8in; display: grid; margin: 0 auto;
        grid-template-rows: auto repeat(4, 1fr); gap: 0.07in; break-after: page; }
.page:last-child { break-after: auto; }
.top { display: flex; align-items: flex-end; gap: 0.15in; border-bottom: 3px solid #000;
       padding-bottom: 2px; }
.top h1 { margin: 0; font-size: 22px; letter-spacing: 0.18em; white-space: nowrap; }
.top .f { flex: 1; border: 1.5px solid #000; padding: 2px 4px; min-height: 0.25in;
          text-transform: uppercase; font-size: 8px; font-weight: bold; }
.unit { border: 2px solid #000; display: flex; flex-direction: column; min-height: 0; }
.unit header { border-bottom: 1.5px solid #000; padding: 2px 6px; font-size: 12px;
               text-transform: uppercase; display: flex; gap: 4px; align-items: baseline; }
.sign { font-weight: bold; letter-spacing: 0.04em; }
.frame { margin-left: auto; font-size: 8px; }
.body { display: flex; flex: 1; min-height: 0; }
.left { width: 2.0in; border-right: 1.5px solid #000; display: flex; flex-direction: column; }
.stats { display: grid; grid-template-columns: 1fr 1fr; border-bottom: 1.5px solid #000; }
.stats div { display: flex; justify-content: space-between; align-items: baseline;
             padding: 1px 6px; border-bottom: 1px solid #000; }
.stats div:nth-child(odd) { border-right: 1px solid #000; }
.stats div:nth-child(n+3) { border-bottom: 0; }
.stats b:empty { min-height: 0.24in; }
.stats span { font-weight: bold; font-size: 9px; } .stats b { font-size: 15px; }
.trk { padding: 2px 5px 3px; border-bottom: 1px solid #000; flex: 1; }
.trk:last-child { border-bottom: 0; }
.trk span { font-weight: bold; font-size: 8px; text-transform: uppercase; display: block; }
.circles { display: flex; flex-wrap: wrap; gap: 3px 2px; margin-top: 3px; }
.o { width: 0.165in; height: 0.165in; border: 1.4px solid #000; border-radius: 50%;
     display: inline-flex; align-items: center; justify-content: center;
     font-style: normal; font-size: 6px; color: #777; }
.platwrap { flex: 1; min-width: 0; overflow-x: auto; display: flex; }
.plat { flex: 1; width: 100%; border-collapse: collapse; table-layout: fixed; }
.plat th { text-align: left; text-transform: uppercase; font-size: 8px;
           border-bottom: 1.5px solid #000; padding: 1px 4px; }
.plat td { border-bottom: 1px solid #999; padding: 0 4px; height: 0.2in;
           overflow: hidden; line-height: 1.1; vertical-align: middle; }
.plat tr:last-child td { border-bottom: 0; }
.s { width: 56%; } .w { width: 27%; } .d { width: 6%; text-align: center; }
.c { width: 11%; text-align: right; }
.plat td.c { font-size: 8px; white-space: nowrap; }
.plat td.w { font-weight: bold; } .plat td.s { font-size: 8.5px; }
.foot2 { display: flex; border-top: 1.5px solid #000; height: 0.3in; }
.notes { flex: 1; padding: 1px 6px; font-size: 8px; }
.total { width: 1.6in; border-left: 1.5px solid #000; padding: 1px 6px; font-size: 8px;
         text-transform: uppercase; }
.total b { display: block; font-size: 13px; text-align: right; }
.lead { margin-left: 6px; padding: 0 5px; border: 1.5px solid #000; font-size: 8px;
        font-weight: bold; letter-spacing: 0.08em; }
.notes span { margin-right: 4px; font-weight: bold; font-size: 8px; text-transform: uppercase; }
.foot { position: absolute; font-size: 7px; color: #555; }
@media print { .foot { display: none; } }
@media screen { .foot { position: static; } body { background: #ddd; padding: 12px; }
  .page { background: #fff; padding: 0.15in; margin-bottom: 14px; height: auto;
          min-height: 10.2in; box-shadow: 0 1px 6px #0006; } }
"""


BLANK_HEAT, BLANK_HP, BLANK_ROWS = 20, 10, 8


def _blank_block(n: int) -> str:
    """An empty unit block to fill in by hand: same layout, no stats, long trackers."""
    plat = "<tr><td class='w'></td><td class='d'></td><td class='s'></td><td class='c'></td></tr>"
    return f"""
<section class="unit">
  <header><b>{n:02d}</b> &ndash; <span class="sign">Call sign</span>
    <span class="frame">Frame: L / M / H &middot; PF ___</span></header>
  <div class="body">
    <div class="left">
      <div class="stats">
        <div><span>S</span><b></b></div><div><span>CS</span><b></b></div>
        <div><span>AR</span><b></b></div><div><span>HL</span><b></b></div>
      </div>
      <div class="trk"><span>Heat tracker</span>{_circles(BLANK_HEAT, label=True)}</div>
      <div class="trk"><span>HP tracker</span>{_circles(BLANK_HP, label=True)}</div>
    </div>
    <div class="platwrap"><table class="plat">
      <thead><tr><th class="w">Platforms</th><th class="d">Dmg</th>
        <th class="s">Special</th><th class="c">Cost</th></tr></thead>
      <tbody>{plat * BLANK_ROWS}</tbody>
    </table></div>
  </div>
  <div class="foot2">
    <div class="notes"><span>Notes</span></div>
    <div class="total"><span>Total cost</span> <b></b></div>
  </div>
</section>"""


def render_sheet(rules: Ruleset, *, seed: int, pages: int = 1, paper: str = "letter",
                 supported_only: bool = False, blank: bool = False) -> str:
    rng = Rng.from_seed(seed)
    out = []
    for _ in range(pages):
        blocks = ""
        if blank:
            blocks = "".join(_blank_block(i + 1) for i in range(PER_PAGE))
        else:
            units, perk = generate_squad(rules, rng, 0, n=PER_PAGE, id_prefix="M",
                                         supported_only=supported_only)
            blocks = "".join(
                _block(rules, u, i + 1, perk if i == 0 else None) for i, u in enumerate(units)
            )
        out.append(
            '<div class="page"><div class="top"><h1>FLAMES OF ORION</h1>'
            '<div class="f">Combat unit name</div><div class="f">Faction</div>'
            f'<div class="f">Player</div></div>{blocks}</div>'
        )
    flags = "--blank" if blank else f"--seed {seed}"
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        f"<title>{'Blank unit sheet' if blank else f'Random mechs (seed {seed})'}</title>"
        f'<style>{_CSS.replace("__PAPER__", paper)}</style><body>'
        + "".join(out)
        + f'<p class="foot">foosim-sheet {flags} --pages {pages}</p></body></html>'
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Printable random Flames of Orion mech sheets")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--pages", type=int, default=1, help="squads (4 mechs each)")
    ap.add_argument("--paper", default="letter", help="CSS page size, e.g. letter or A4")
    ap.add_argument("--out", type=Path, default=Path("mechs.html"))
    ap.add_argument("--blank", action="store_true",
                    help=f"empty sheets to fill by hand ({BLANK_HEAT} heat, {BLANK_HP} HP circles)")
    ap.add_argument("--supported-only", action="store_true",
                    help="skip gear the sim does not implement yet (default: whole Black Market)")
    args = ap.parse_args(argv)
    html = render_sheet(load_rules(), seed=args.seed, pages=args.pages, paper=args.paper,
                        supported_only=args.supported_only, blank=args.blank)
    args.out.write_text(html, encoding="utf-8")
    what = "blank unit blocks" if args.blank else f"mechs, seed {args.seed}"
    print(f"wrote {args.out} ({args.pages * PER_PAGE} {what})")


if __name__ == "__main__":  # pragma: no cover
    main()
