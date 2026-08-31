"""Bot policies. A policy maps a GameState (during the activation phase) to one
decision: ``ActivateUnit`` / an action / ``EndActivation`` / ``Pass``.

``RandomPolicy`` is the regression baseline; smarter policies go in new classes so
historical analysis stays comparable. ``RandomPolicy(bolster_bias=0.0)`` reproduces
the pre-bolster baseline.
"""

from __future__ import annotations

from foosim.engine import hexgrid
from foosim.engine.actions import (
    ActivateUnit,
    DisengageAction,
    EndActivation,
    MeleeAttackAction,
    MoveAction,
    PurgeHeatAction,
    RangedAttackAction,
)
from foosim.engine.legal import legal_actions
from foosim.engine.resolve import plan_attack
from foosim.engine.rng import Rng
from foosim.engine.state import GameState

__all__ = ["GreedyPolicy", "Policy", "RandomPolicy"]

_EPS = 0.01


class Policy:
    def decide(self, state: GameState):  # pragma: no cover - interface
        raise NotImplementedError


class RandomPolicy(Policy):
    """Picks uniformly among legal actions; ends activations early at random.

    ``bolster_bias`` (0..1): when the unit has HEAT headroom, probability of
    steering the pick toward a bolstered variant - table play bolsters almost
    every activation until near overheat, so the default leans that way.
    """

    def __init__(self, rules, seed: int = 0, *, bolster_bias: float = 0.75) -> None:
        self.rules = rules
        self.rng = Rng.from_seed(seed)
        self.bolster_bias = bolster_bias

    def decide(self, state: GameState):
        side = state.active_side
        if state.activating_unit is None:
            pending = [
                u for u in state.units.values()
                if u.side == side and not u.activated and not u.out_of_action
            ]
            return ActivateUnit(self.rng.choice(pending).id)

        unit = state.units[state.activating_unit]
        if state.actions_taken >= self.rules.game["actions_per_activation"]:
            return EndActivation()
        options = legal_actions(state, unit, self.rules)
        if not options:
            return EndActivation()
        if state.actions_taken >= 1 and self.rng.d6() <= 2:
            return EndActivation()

        # a bolstered 2nd action adds up to +2 HEAT; only lean in with room to spare
        headroom = unit.stat("heat_limit") - unit.heat - state.actions_taken
        want_bolster = headroom >= 3 and self.rng.random() < self.bolster_bias
        pool = [a for a in options if bool(getattr(a, "bolster", None)) == want_bolster]
        return self.rng.choice(pool or options)


class GreedyPolicy(Policy):
    """A heuristic player: approach, fire the best weapon, bolster while there is
    HEAT headroom, purge when hot, disengage when hurt. Beats ``RandomPolicy``
    handily; the baseline for M8 analysis. Deterministic per ``seed``."""

    def __init__(self, rules, seed: int = 0, *, aggression: float = 1.0) -> None:
        self.rules = rules
        self.rng = Rng.from_seed(seed)
        self.aggression = aggression

    # -- entry point ---------------------------------------------------
    def decide(self, state: GameState):
        side = state.active_side
        pending = [
            u for u in state.units.values()
            if u.side == side and not u.activated and not u.out_of_action
        ]
        if state.activating_unit is None:
            # front-liners (closest to an enemy) go first
            u = min(pending, key=lambda x: self._nearest_dist(state, x))
            return ActivateUnit(u.id)

        unit = state.units[state.activating_unit]
        if state.actions_taken >= self.rules.game["actions_per_activation"]:
            return EndActivation()
        los_cache: dict = {}  # reused across the many variants of one shot
        scored = [
            (self._score(state, unit, a, los_cache), a)
            for a in legal_actions(state, unit, self.rules)
        ]
        scored = [(sc, a) for sc, a in scored if sc > _EPS]
        if not scored:
            return EndActivation()
        best = max(sc for sc, _ in scored)
        top = [a for sc, a in scored if sc >= best - 0.05]
        return self.rng.choice(top)

    # -- helpers -----------------------------------------------------
    def _enemies(self, state, u):
        return [e for e in state.units.values() if e.side != u.side and not e.out_of_action]

    def _nearest(self, state, u):
        es = self._enemies(state, u)
        return min(es, key=lambda e: hexgrid.distance(u.pos, e.pos)) if es else None

    def _nearest_dist(self, state, u):
        e = self._nearest(state, u)
        return hexgrid.distance(u.pos, e.pos) if e else 1 << 20

    def _heat_penalty(self, unit) -> float:
        room = unit.stat("heat_limit") - unit.heat
        if room > 4:
            return 0.4
        if room > 2:
            return 1.6
        return 6.0

    # -- scoring ---------------------------------------------------
    def _score(self, state, u, a, los_cache: dict | None = None) -> float:
        pen = self._heat_penalty(u)
        heat_cost = 1 if state.actions_taken >= 1 else 0
        heat_cost += 1 if getattr(a, "bolster", None) else 0

        if isinstance(a, (RangedAttackAction, MeleeAttackAction)):
            return self._score_attack(state, u, a, pen, heat_cost, los_cache)
        if isinstance(a, MoveAction):
            e = self._nearest(state, u)
            if e is None:
                return 0.0
            here = hexgrid.distance(u.pos, e.pos)
            there = hexgrid.distance(a.path[-1], e.pos)
            hurt = u.hp <= max(1, u.hp_max // 3)
            val = (here - there) * (-0.4 if (hurt and here <= 1) else 0.35)
            if a.shot_target:  # snap shot rider
                sp = plan_attack(state, u.id, a.shot_target, a.shot_weapon_index or 0,
                                 self.rules, kind="ranged", bolster="snap_shot")
                if sp.legal:
                    val += sp.hit_chance * sp.expected_damage_through
            return val - heat_cost * pen * 0.5
        if isinstance(a, DisengageAction):
            hurt = u.hp <= max(1, u.hp_max // 3)
            val = (1.6 if hurt else 0.25) + (0.5 if a.bolster == "dodge" else 0.0)
            return val - (pen * 0.5 if a.bolster else 0.0)
        if isinstance(a, PurgeHeatAction):
            room = u.stat("heat_limit") - u.heat
            if room <= 2:
                return 5.0 + (2.0 if a.bolster == "reboot" and state.actions_taken == 0 else 0.0)
            return 1.0 if room <= 4 else 0.0
        return 0.0

    def _score_attack(self, state, u, a, pen, heat_cost, los_cache=None) -> float:
        t = state.units.get(a.target_id)
        if t is None or t.out_of_action:
            return 0.0
        kind = "ranged" if isinstance(a, RangedAttackAction) else "melee"
        if a.bolster == "ram":
            return 0.8 - heat_cost * pen  # ~1 avg dmg, self-damage; rarely worth it
        multi = a.bolster in ("unleash_hell", "fury")
        plan_bolster = None if multi else a.bolster
        p = plan_attack(state, u.id, a.target_id, a.weapon_index, self.rules,
                        kind=kind, bolster=plan_bolster, los_cache=los_cache)
        if not p.legal:
            return 0.0
        n = 1
        if multi:
            n = sum(1 for w in u.weapons
                    if w.kind == kind and not w.used_this_turn and not w.disabled)
        dmg = p.expected_damage_through * (0.9 * n if multi else 1.0)
        val = p.hit_chance * dmg * self.aggression + p.catastrophic_chance * 3.0
        if dmg >= t.hp:  # a plausible kill
            val += 4.0
        return val - heat_cost * pen
