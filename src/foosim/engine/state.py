"""Game state dataclasses for the Flames of Orion engine. Pure, stdlib only.

Everything here is plain data with explicit ``to_dict`` / ``from_dict`` that round
-trips through JSON unchanged - this is the contract a Godot / C# port reuses, and
the unit of storage for replay snapshots.

Design:
  * Unit stat fields (``hp_max``, ``ar``, ``cs``, ``speed``, ``heat_limit``,
    ``platforms``) are the *battle-start effective* values - the unit builder /
    generator bakes static upgrades (Armor Mk, Thrusters, ...) into them.
  * Temporary in-play effects live in ``modifiers`` (int deltas by stat name) and
    ``statuses`` (flags / counters). Read an effective stat with ``Unit.stat()``.
  * Weapon / upgrade *behaviours* are looked up from the Ruleset by id at resolve
    time; only their numeric stat effects are baked.

``GameState`` also satisfies ``engine.visibility.Board`` so
``line_of_sight(state, a, b, cfg)`` works directly.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from foosim.engine.hexgrid import Hex

__all__ = ["GameState", "MapSpec", "TerrainHex", "Unit", "WeaponInstance"]

TERRAIN_TAGS = frozenset({"blocking", "cover", "destructible", "indestructible"})


def _h2l(h: Hex) -> list[int]:
    return [h.q, h.r]


def _l2h(pair) -> Hex:
    return Hex(int(pair[0]), int(pair[1]))


# ---------------------------------------------------------------------------


@dataclass
class WeaponInstance:
    weapon_id: str
    kind: str  # "ranged" | "melee"
    ammo_id: str | None = None
    used_this_turn: bool = False
    disabled: bool = False
    burnout: bool = False  # Power Weapon lost AP / Energy Sword degraded

    def to_dict(self) -> dict:
        return {
            "weapon_id": self.weapon_id,
            "kind": self.kind,
            "ammo_id": self.ammo_id,
            "used_this_turn": self.used_this_turn,
            "disabled": self.disabled,
            "burnout": self.burnout,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WeaponInstance:
        return cls(
            weapon_id=d["weapon_id"],
            kind=d["kind"],
            ammo_id=d.get("ammo_id"),
            used_this_turn=bool(d.get("used_this_turn", False)),
            disabled=bool(d.get("disabled", False)),
            burnout=bool(d.get("burnout", False)),
        )


@dataclass
class Unit:
    id: str
    side: int
    name: str
    profile: str  # provenance, e.g. "mech.medium" / "ground.infantry"

    # battle-start effective stats
    hp_max: int
    ar: int
    cs: int
    speed: int
    heat_limit: int
    platforms: int

    # dynamic
    hp: int = 0
    heat: int = 0
    pos: Hex = Hex(0, 0)
    facing: int = 0

    # loadout
    weapons: list[WeaponInstance] = field(default_factory=list)
    upgrades: list[str] = field(default_factory=list)

    # runtime effects
    modifiers: dict[str, int] = field(default_factory=dict)
    statuses: dict[str, int] = field(default_factory=dict)
    reactive_armor_left: int = 0

    # baked behaviour flags (set by the builder from profile + upgrades)
    explodes: bool = True
    can_ram: bool = True
    ignores_terrain_on_move: bool = False
    heat_check_table: str = "check_default"

    # activation state
    activated: bool = False
    out_of_action: bool = False

    def __post_init__(self) -> None:
        if self.hp == 0:
            self.hp = self.hp_max

    def stat(self, name: str) -> int:
        """Effective value of a stat: base field + accumulated modifier delta."""
        return getattr(self, name) + self.modifiers.get(name, 0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "side": self.side,
            "name": self.name,
            "profile": self.profile,
            "hp_max": self.hp_max,
            "ar": self.ar,
            "cs": self.cs,
            "speed": self.speed,
            "heat_limit": self.heat_limit,
            "platforms": self.platforms,
            "hp": self.hp,
            "heat": self.heat,
            "pos": _h2l(self.pos),
            "facing": self.facing,
            "weapons": [w.to_dict() for w in self.weapons],
            "upgrades": list(self.upgrades),
            "modifiers": dict(self.modifiers),
            "statuses": dict(self.statuses),
            "reactive_armor_left": self.reactive_armor_left,
            "explodes": self.explodes,
            "can_ram": self.can_ram,
            "ignores_terrain_on_move": self.ignores_terrain_on_move,
            "heat_check_table": self.heat_check_table,
            "activated": self.activated,
            "out_of_action": self.out_of_action,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Unit:
        return cls(
            id=d["id"],
            side=int(d["side"]),
            name=d["name"],
            profile=d["profile"],
            hp_max=int(d["hp_max"]),
            ar=int(d["ar"]),
            cs=int(d["cs"]),
            speed=int(d["speed"]),
            heat_limit=int(d["heat_limit"]),
            platforms=int(d["platforms"]),
            hp=int(d["hp"]),
            heat=int(d["heat"]),
            pos=_l2h(d["pos"]),
            facing=int(d["facing"]),
            weapons=[WeaponInstance.from_dict(w) for w in d.get("weapons", [])],
            upgrades=list(d.get("upgrades", [])),
            modifiers={k: int(v) for k, v in d.get("modifiers", {}).items()},
            statuses={k: int(v) for k, v in d.get("statuses", {}).items()},
            reactive_armor_left=int(d.get("reactive_armor_left", 0)),
            explodes=bool(d.get("explodes", True)),
            can_ram=bool(d.get("can_ram", True)),
            ignores_terrain_on_move=bool(d.get("ignores_terrain_on_move", False)),
            heat_check_table=d.get("heat_check_table", "check_default"),
            activated=bool(d.get("activated", False)),
            out_of_action=bool(d.get("out_of_action", False)),
        )


@dataclass
class TerrainHex:
    pos: Hex
    tags: set[str] = field(default_factory=set)
    height: float = 1.0
    damage_marks: int = 0  # hits taken this turn (destroyed on 2nd, or 3+ in one action)
    destroyed: bool = False

    @property
    def destructible(self) -> bool:
        return "destructible" in self.tags

    def to_dict(self) -> dict:
        return {
            "pos": _h2l(self.pos),
            "tags": sorted(self.tags),
            "height": self.height,
            "damage_marks": self.damage_marks,
            "destroyed": self.destroyed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TerrainHex:
        bad = set(d.get("tags", [])) - TERRAIN_TAGS
        if bad:
            raise ValueError(f"unknown terrain tags: {sorted(bad)}")
        return cls(
            pos=_l2h(d["pos"]),
            tags=set(d.get("tags", [])),
            height=float(d.get("height", 1.0)),
            damage_marks=int(d.get("damage_marks", 0)),
            destroyed=bool(d.get("destroyed", False)),
        )


@dataclass
class MapSpec:
    """Static board geometry (odd-r rectangular). Live terrain is on GameState."""

    cols: int
    rows: int
    name: str = "untitled"
    elevation: dict[Hex, int] = field(default_factory=dict)  # sparse; absent -> 0
    deploy_zones: dict[int, tuple[Hex, ...]] = field(default_factory=dict)

    def cells(self) -> set[Hex]:
        from foosim.engine.hexgrid import from_offset_oddr

        return {
            from_offset_oddr(c, r) for r in range(self.rows) for c in range(self.cols)
        }

    def in_bounds(self, h: Hex) -> bool:
        from foosim.engine.hexgrid import to_offset_oddr

        c, r = to_offset_oddr(h)
        return 0 <= c < self.cols and 0 <= r < self.rows

    def to_dict(self) -> dict:
        return {
            "cols": self.cols,
            "rows": self.rows,
            "name": self.name,
            "elevation": [[_h2l(h), v] for h, v in sorted(self.elevation.items())],
            "deploy_zones": {
                str(side): [_h2l(h) for h in hexes]
                for side, hexes in sorted(self.deploy_zones.items())
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> MapSpec:
        return cls(
            cols=int(d["cols"]),
            rows=int(d["rows"]),
            name=d.get("name", "untitled"),
            elevation={_l2h(k): int(v) for k, v in d.get("elevation", [])},
            deploy_zones={
                int(side): tuple(_l2h(h) for h in hexes)
                for side, hexes in d.get("deploy_zones", {}).items()
            },
        )


@dataclass
class GameState:
    mapspec: MapSpec
    mission: str = "warzone"
    rng_state: int = 0

    round: int = 1
    phase: str = "setup"
    phase_index: int = 0
    initiative: tuple[int, ...] = (0, 1)
    active_side: int = 0
    turn_in_phase: int = 0

    units: dict[str, Unit] = field(default_factory=dict)
    terrain: dict[Hex, TerrainHex] = field(default_factory=dict)

    # current-activation bookkeeping (managed by engine.phases)
    activating_unit: str | None = None
    actions_taken: int = 0
    bolstered_count: int = 0
    round_first_finisher: int | None = None

    finished_first_last_round: int | None = None
    pass_tokens: dict[int, int] = field(default_factory=dict)

    log_counter: int = 0
    winner: int | None = None
    end_reason: str | None = None

    def copy(self) -> GameState:
        # mapspec is immutable during a game - share it instead of deep-copying
        # its (large, static) elevation / deploy-zone dicts every step.
        return copy.deepcopy(self, {id(self.mapspec): self.mapspec})

    # -- convenience ----------------------------------------------------
    def unit_at(self, h: Hex) -> Unit | None:
        for u in self.units.values():
            if not u.out_of_action and u.pos == h:
                return u
        return None

    def live_units(self, side: int | None = None) -> list[Unit]:
        return [
            u
            for u in self.units.values()
            if not u.out_of_action and (side is None or u.side == side)
        ]

    def sides(self) -> list[int]:
        return sorted({u.side for u in self.units.values()})

    # -- visibility.Board protocol -----------------------------------
    def _terrain_live(self, h: Hex) -> TerrainHex | None:
        t = self.terrain.get(h)
        return t if (t is not None and not t.destroyed) else None

    def blocks_los(self, h: Hex) -> bool:
        t = self._terrain_live(h)
        return t is not None and "blocking" in t.tags

    def is_cover(self, h: Hex) -> bool:
        t = self._terrain_live(h)
        return t is not None and "cover" in t.tags

    def has_model(self, h: Hex) -> bool:
        return self.unit_at(h) is not None

    def column_height(self, h: Hex) -> float:
        base = float(self.mapspec.elevation.get(h, 0))
        t = self._terrain_live(h)
        return base + (t.height if t is not None else 0.0)

    # -- serialization ---------------------------------------------
    def to_dict(self) -> dict:
        return {
            "mapspec": self.mapspec.to_dict(),
            "mission": self.mission,
            "rng_state": self.rng_state,
            "round": self.round,
            "phase": self.phase,
            "phase_index": self.phase_index,
            "initiative": list(self.initiative),
            "active_side": self.active_side,
            "turn_in_phase": self.turn_in_phase,
            "units": {uid: u.to_dict() for uid, u in self.units.items()},
            "terrain": [t.to_dict() for t in self.terrain.values()],
            "activating_unit": self.activating_unit,
            "actions_taken": self.actions_taken,
            "bolstered_count": self.bolstered_count,
            "round_first_finisher": self.round_first_finisher,
            "finished_first_last_round": self.finished_first_last_round,
            "pass_tokens": {str(k): v for k, v in sorted(self.pass_tokens.items())},
            "log_counter": self.log_counter,
            "winner": self.winner,
            "end_reason": self.end_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> GameState:
        terrain_list = [TerrainHex.from_dict(t) for t in d.get("terrain", [])]
        return cls(
            mapspec=MapSpec.from_dict(d["mapspec"]),
            mission=d.get("mission", "warzone"),
            rng_state=int(d.get("rng_state", 0)),
            round=int(d.get("round", 1)),
            phase=d.get("phase", "setup"),
            phase_index=int(d.get("phase_index", 0)),
            initiative=tuple(int(x) for x in d.get("initiative", (0, 1))),
            active_side=int(d.get("active_side", 0)),
            turn_in_phase=int(d.get("turn_in_phase", 0)),
            units={uid: Unit.from_dict(u) for uid, u in d.get("units", {}).items()},
            terrain={t.pos: t for t in terrain_list},
            activating_unit=d.get("activating_unit"),
            actions_taken=int(d.get("actions_taken", 0)),
            bolstered_count=int(d.get("bolstered_count", 0)),
            round_first_finisher=d.get("round_first_finisher"),
            finished_first_last_round=d.get("finished_first_last_round"),
            pass_tokens={int(k): int(v) for k, v in d.get("pass_tokens", {}).items()},
            log_counter=int(d.get("log_counter", 0)),
            winner=d.get("winner"),
            end_reason=d.get("end_reason"),
        )
