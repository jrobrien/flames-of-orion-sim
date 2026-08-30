"""Load and query ``data/rules.toml`` - the tunable rules parameters.

``Ruleset`` is a thin typed view over the parsed dict plus a ``content_hash`` so
analysis runs are traceable and replays can detect a ruleset change.
``with_overrides`` deep-merges dotted-path overrides for A/B experiments.

Stdlib only (``tomllib`` is 3.11+).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tomllib
from pathlib import Path
from typing import Any

__all__ = ["DEFAULT_RULES_PATH", "Ruleset", "load"]

# rules.py -> engine -> foosim -> src -> <repo root>
DEFAULT_RULES_PATH = Path(__file__).resolve().parents[3] / "data" / "rules.toml"


def _resolve_path(path: str | os.PathLike | None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("FOOSIM_RULES")
    if env:
        return Path(env)
    return DEFAULT_RULES_PATH
    # TODO(pkg): also fall back to an importlib.resources copy once data/ is
    # shipped inside the wheel (see PLAN.md section 9).


def _content_hash(raw: dict) -> str:
    blob = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


class Ruleset:
    def __init__(self, raw: dict) -> None:
        self.raw: dict = raw
        self.ranged_weapons: dict[str, dict] = {w["id"]: w for w in raw.get("ranged_weapons", [])}
        self.melee_weapons: dict[str, dict] = {w["id"]: w for w in raw.get("melee_weapons", [])}
        self.ammo: dict[str, dict] = {a["id"]: a for a in raw.get("ammo", [])}
        self.upgrades: dict[str, dict] = {u["id"]: u for u in raw.get("upgrades", [])}
        self.content_hash: str = _content_hash(raw)
        self._validate()

    # -- construction -------------------------------------------------
    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> Ruleset:
        p = _resolve_path(path)
        with p.open("rb") as f:
            return cls(tomllib.load(f))

    def with_overrides(self, overrides: dict[str, Any]) -> Ruleset:
        """New Ruleset with dotted-path values replaced, e.g.
        ``{"to_hit.long_range_inches": 8}``. Cannot target list elements
        (weapons/ammo/upgrades) yet - see PLAN.md section 8 / M8."""
        raw = copy.deepcopy(self.raw)
        for dotted, value in overrides.items():
            parts = dotted.split(".")
            node = raw
            for key in parts[:-1]:
                nxt = node.get(key)
                if not isinstance(nxt, dict):
                    nxt = {}
                    node[key] = nxt
                node = nxt
            node[parts[-1]] = value
        return Ruleset(raw)

    # -- validation -------------------------------------------------
    def _validate(self) -> None:
        problems: list[str] = []
        for name, table, n in [
            ("ranged_weapons", self.ranged_weapons, 8),
            ("melee_weapons", self.melee_weapons, 8),
            ("ammo", self.ammo, 6),
            ("upgrades", self.upgrades, 20),
        ]:
            if len(table) != n:
                problems.append(f"{name}: expected {n} entries, got {len(table)}")
        cat = set(self.raw.get("catastrophic", {}))
        if cat != {str(n) for n in range(2, 13)}:
            problems.append(f"catastrophic: expected keys 2..12, got {sorted(cat)}")
        if not self.raw.get("game", {}).get("phase_order"):
            problems.append("game.phase_order is missing or empty")
        for pname in ("heat", "to_hit", "explode", "frames"):
            if pname not in self.raw:
                problems.append(f"missing [{pname}] table")
        if problems:
            raise ValueError("invalid rules.toml:\n  " + "\n  ".join(problems))

    # -- accessors -------------------------------------------------
    @property
    def game(self) -> dict:
        return self.raw["game"]

    @property
    def to_hit(self) -> dict:
        return self.raw["to_hit"]

    @property
    def heat(self) -> dict:
        return self.raw["heat"]

    @property
    def explode(self) -> dict:
        return self.raw["explode"]

    @property
    def visibility(self) -> dict:
        return self.raw.get("visibility", {})

    @property
    def phase_order(self) -> list[str]:
        return list(self.raw["game"]["phase_order"])

    def frame(self, name: str) -> dict:
        return self.raw["frames"][name]

    def frame_for_roll(self, d6: int) -> str:
        return self.raw["frames"]["roll_table"][str(d6)]

    def ground_force(self, name: str) -> dict:
        return self.raw["ground_forces"][name]

    def weapon(self, weapon_id: str) -> dict:
        if weapon_id in self.ranged_weapons:
            return self.ranged_weapons[weapon_id]
        if weapon_id in self.melee_weapons:
            return self.melee_weapons[weapon_id]
        raise KeyError(f"unknown weapon id: {weapon_id!r}")

    def weapon_kind(self, weapon_id: str) -> str:
        if weapon_id in self.ranged_weapons:
            return "ranged"
        if weapon_id in self.melee_weapons:
            return "melee"
        raise KeyError(f"unknown weapon id: {weapon_id!r}")

    def ammo_spec(self, ammo_id: str) -> dict:
        return self.ammo[ammo_id]

    def upgrade(self, upgrade_id: str) -> dict:
        return self.upgrades[upgrade_id]

    def catastrophic(self, roll_2d6: int) -> dict:
        return self.raw["catastrophic"][str(roll_2d6)]

    def heat_check_table(self, name: str = "check_default") -> dict[int, int]:
        return {int(k): int(v) for k, v in self.raw["heat"][name].items()}

    def hex_per_inch(self) -> int:
        return int(self.raw.get("meta", {}).get("hex_per_inch", 1))

    def inches_to_hexes(self, inches: float) -> int:
        return int(round(inches * self.hex_per_inch()))


def load(path: str | os.PathLike | None = None) -> Ruleset:
    return Ruleset.load(path)
