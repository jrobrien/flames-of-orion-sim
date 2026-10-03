"""Turn engine data into strings and colours for the UI. Pure - no imgui.

Colours are ``(r, g, b, a)`` floats in ``[0, 1]``; the imgui layer converts.
"""

from __future__ import annotations

from foosim.engine.events import Event
from foosim.engine.state import Unit

__all__ = [
    "NEUTRAL",
    "SIDE_COLORS",
    "event_color",
    "event_line",
    "heat_fraction",
    "unit_label",
    "unit_stat_lines",
]

SIDE_COLORS: dict[int, tuple[float, float, float, float]] = {
    0: (0.36, 0.60, 0.96, 1.0),
    1: (0.96, 0.48, 0.32, 1.0),
}
NEUTRAL = (0.62, 0.62, 0.66, 1.0)
_DIM = (0.55, 0.55, 0.58, 1.0)

_EVENT_COLORS: dict[str, tuple[float, float, float, float]] = {
    "damage": (0.95, 0.38, 0.38, 1.0),
    "critical": (1.0, 0.82, 0.25, 1.0),
    "catastrophic": (1.0, 0.55, 0.15, 1.0),
    "explosion": (1.0, 0.45, 0.12, 1.0),
    "explode_check": (1.0, 0.55, 0.30, 1.0),
    "out_of_action": (0.85, 0.22, 0.22, 1.0),
    "overheat": (1.0, 0.35, 0.12, 1.0),
    "heat_gain": (0.90, 0.62, 0.34, 1.0),
    "heat_purge": (0.45, 0.80, 0.85, 1.0),
    "phase_start": (0.55, 0.72, 0.92, 1.0),
    "initiative": (0.55, 0.72, 0.92, 1.0),
    "game_over": (0.45, 0.92, 0.55, 1.0),
    "game_start": (0.45, 0.92, 0.55, 1.0),
    "move": (0.70, 0.72, 0.76, 1.0),
    "free_attack": (0.85, 0.60, 0.95, 1.0),
    "ricochet": (0.95, 0.65, 0.30, 1.0),
}


def side_color(side: int) -> tuple[float, float, float, float]:
    return SIDE_COLORS.get(side, NEUTRAL)


def event_color(e: Event) -> tuple[float, float, float, float]:
    if e.kind == "attack":
        outcome = e.data.get("outcome")
        if outcome == "crit":
            return _EVENT_COLORS["critical"]
        if outcome == "hit":
            return (0.95, 0.75, 0.45, 1.0)
        return _DIM
    return _EVENT_COLORS.get(e.kind, NEUTRAL)


def unit_label(u: Unit) -> str:
    return f"{u.id} · {u.name}"


def heat_fraction(u: Unit) -> float:
    limit = max(1, u.stat("heat_limit"))
    return max(0.0, min(1.0, u.heat / limit))


def unit_stat_lines(u: Unit) -> list[str]:
    lines = [
        f"S {u.stat('speed')}   CS {u.stat('cs')}+   AR {u.stat('ar')}+",
        f"HP {u.hp}/{u.hp_max}   HEAT {u.heat}/{u.stat('heat_limit')}   PF {u.platforms}",
    ]
    for w in u.weapons:
        flags = []
        if w.used_this_turn:
            flags.append("used")
        if w.disabled:
            flags.append("disabled")
        if w.ammo_id:
            flags.append(w.ammo_id)
        suffix = f"  ({', '.join(flags)})" if flags else ""
        lines.append(f"  [{w.kind[0].upper()}] {w.weapon_id}{suffix}")
    if u.upgrades:
        lines.append("  up: " + ", ".join(u.upgrades))
    active = [k for k, v in u.statuses.items() if v]
    if active:
        lines.append("  status: " + ", ".join(sorted(active)))
    mods = {k: v for k, v in u.modifiers.items() if v}
    if mods:
        lines.append("  mods: " + ", ".join(f"{k}{v:+d}" for k, v in sorted(mods.items())))
    if u.out_of_action:
        lines.append("  ** OUT OF ACTION **")
    return lines


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "?"


# one-line templates; missing keys render as "?"
_TEMPLATES: dict[str, str] = {
    "game_start": "-- game start ({rounds} rounds) --",
    "initiative": "initiative {rolls} -> order {order}",
    "activation_start": "{unit} activates (side {side})",
    "activation_end": "{unit} activation ends",
    "move": "{unit} {kind} to {to} (cost {cost})",
    "dice_roll": "{unit} rolls {notation} for {purpose}: {results} = {total}",
    "free_attack": "{attacker} free attack on {target} ({reason})",
    "critical": "CRIT {attacker} -> {target} (+{bonus_damage} dmg)",
    "catastrophic": "CATASTROPHIC on {target}: {result_name}",
    "armor_save": "{target} saves {save_tn}+ {rolls}: {through} through, {ignored} soaked",
    "damage": "{target} takes {amount} ({hp_before} -> {hp_after} HP) [{weapon}]",
    "damage_soaked": "{target} soaks {amount} ({source})",
    "heat_gain": "{unit} +{amount} heat ({reason}) -> {heat_after}",
    "heat_purge": "{unit} purges {amount} heat ({mode}) -> {heat_after}",
    "overheat": "{unit} OVERHEAT {heat}/{heat_limit}",
    "explode_check": "{unit} explode check: rolled {roll} -> {exploded}",
    "self_destruct": "{unit} SELF-DESTRUCTS at {heat} heat",
    "explosion": "{unit} EXPLODES: {damage} dmg r{radius}, hits {affected}",
    "out_of_action": "{unit} OUT OF ACTION ({cause})",
    "status_applied": "{unit} gains {status}",
    "status_cleared": "{unit} loses {status}",
    "modifier_applied": "{unit} {stat} {delta} ({source})",
    "weapon_disabled": "{unit} weapon disabled: {weapon}",
    "ricochet": "ricochet hits {target} for {amount}",
    "pass": "side {side} passes",
    "side_finished": "side {side} finished activating first",
}


def event_line(e: Event) -> str:
    d, k = e.data, e.kind
    if k == "phase_start":
        return f"-- round {d.get('round', '?')}: {d.get('phase', '?')} --"
    if k == "game_over":
        w = d.get("winner")
        who = "draw" if w in (-1, None) else f"side {w}"
        return f"== GAME OVER: {who} ({d.get('reason', '?')}) =="
    if k == "attack":
        flags = "".join(
            f", {t}" for t, on in (("cover", d.get("cover")), ("long", d.get("long_range"))) if on
        )
        atk, tgt = d.get("attacker", "?"), d.get("target", "?")
        cs = d.get("effective_cs", "?")
        return (
            f"{atk} -> {tgt} [{d.get('weapon', '?')}] {d.get('outcome', '?')} "
            f"(roll {d.get('roll', '?')} vs {cs}+{flags})"
        )
    tmpl = _TEMPLATES.get(k)
    if tmpl:
        return tmpl.format_map(_Safe(d))
    extra = " ".join(f"{kk}={vv}" for kk, vv in d.items())
    return f"{k} {extra}".rstrip()
