"""Bot policies. A policy maps a GameState (during the activation phase) to one
decision: ``ActivateUnit`` / an action / ``EndActivation`` / ``Pass``.

``RandomPolicy`` is the regression baseline; smarter policies go in new classes so
historical analysis stays comparable. ``RandomPolicy(bolster_bias=0.0)`` reproduces
the pre-bolster baseline.
"""

from __future__ import annotations

from foosim.engine.actions import ActivateUnit, EndActivation
from foosim.engine.legal import legal_actions
from foosim.engine.rng import Rng
from foosim.engine.state import GameState

__all__ = ["Policy", "RandomPolicy"]


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
