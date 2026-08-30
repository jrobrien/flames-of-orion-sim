"""Bot policies. A policy maps a GameState (during the activation phase) to one
decision: ``ActivateUnit`` / an action / ``EndActivation`` / ``Pass``.

Keep ``RandomPolicy`` stable - it is the regression baseline. Smarter policies go
in new classes so historical analysis stays comparable.
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
    """Picks uniformly among legal actions; ends activations early at random."""

    def __init__(self, rules, seed: int = 0) -> None:
        self.rules = rules
        self.rng = Rng.from_seed(seed)

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
        return self.rng.choice(options)
