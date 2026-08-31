"""The round / phase pipeline.

A round is ``rules.phase_order`` (data, from ``[game] phase_order``). Each name is
bound to a handler here; an unknown name is skipped (emits ``phase_skipped``), so
adding an experimental phase does not break the driver.

``step(state, decision, rules) -> (new_state, [Event])`` advances the game by the
smallest meaningful amount: a whole automatic phase (initiative / heat), or one
activation decision. ``needs_decision(state)`` returns the side that must supply
the next decision, or ``None`` when the next ``step`` is automatic.
"""

from __future__ import annotations

from foosim.engine import resolve
from foosim.engine.actions import ActivateUnit, EndActivation, IllegalAction, Pass, is_action
from foosim.engine.events import Event, emit
from foosim.engine.rng import Rng
from foosim.engine.state import GameState

__all__ = ["needs_decision", "step"]

_AUTOMATIC = {"initiative", "heat"}


def needs_decision(state: GameState) -> int | None:
    if state.winner is not None or state.phase in ("setup", "done"):
        return None
    if state.phase != "activation":
        return None
    if state.activating_unit is not None:
        return state.active_side
    if _pending(state, state.active_side):
        return state.active_side
    if any(_pending(state, sd) for sd in state.sides()):
        # active side is done but another side still has units
        return next(sd for sd in state.sides() if _pending(state, sd))
    return None


def step(state: GameState, decision, rules) -> tuple[GameState, list[Event]]:
    s = state.copy()
    ev: list[Event] = []
    rng = Rng(state=s.rng_state)
    try:
        _step(s, decision, ev, rng, rules)
    finally:
        s.rng_state = rng.state
    return s, ev


def _step(s, decision, ev, rng, rules) -> None:
    if s.winner is not None or s.phase == "done":
        return

    if s.phase == "setup":
        s.round = 1
        s.phase_index = 0
        s.phase = rules.phase_order[0]
        emit(s, ev, "game_start", rounds=rules.game["rounds"], phase_order=rules.phase_order)
        emit(s, ev, "phase_start", phase=s.phase, round=s.round)
        if s.phase == "activation":
            _begin_activation(s)

    name = s.phase
    if name == "initiative":
        _run_initiative(s, ev, rng, rules)
        _advance_phase(s, ev, rules)
    elif name == "heat":
        _run_heat_phase(s, ev, rng, rules)
        _advance_phase(s, ev, rules)
    elif name == "activation":
        _step_activation(s, decision, ev, rng, rules)
    else:
        emit(s, ev, "phase_skipped", phase=name)
        _advance_phase(s, ev, rules)

    _check_victory(s, ev, rules)


# --------------------------------------------------------------------------
# phase transitions
# --------------------------------------------------------------------------


def _advance_phase(s, ev, rules) -> None:
    order = rules.phase_order
    s.phase_index += 1
    if s.phase_index >= len(order):
        s.finished_first_last_round = s.round_first_finisher
        s.round_first_finisher = None
        s.round += 1
        s.phase_index = 0
    s.phase = order[s.phase_index]
    if s.round > rules.game["rounds"]:
        return  # _check_victory finalizes
    emit(s, ev, "phase_start", phase=s.phase, round=s.round)
    if s.phase == "activation":
        _begin_activation(s)


def _begin_activation(s) -> None:
    s.active_side = s.initiative[0]
    s.activating_unit = None
    s.actions_taken = 0
    s.bolstered_count = 0


# --------------------------------------------------------------------------
# initiative
# --------------------------------------------------------------------------


def _run_initiative(s, ev, rng, rules) -> None:
    sides = s.sides()
    rolls: dict[int, int] = {}
    for sd in sides:
        base = rng.d6()
        rolls[sd] = base + (1 if s.finished_first_last_round == sd else 0)
    order = _order_by_roll(sides, rolls, rng)
    s.initiative = tuple(order)
    s.round_first_finisher = None
    for u in s.units.values():
        u.activated = False
    emit(s, ev, "initiative", rolls={str(k): v for k, v in rolls.items()}, order=list(order))


def _order_by_roll(sides, rolls, rng) -> list[int]:
    groups: dict[int, list[int]] = {}
    for sd in sides:
        groups.setdefault(rolls[sd], []).append(sd)
    order: list[int] = []
    for val in sorted(groups, reverse=True):
        tie = groups[val][:]
        rng.shuffle(tie)
        order.extend(tie)
    return order


# --------------------------------------------------------------------------
# activation
# --------------------------------------------------------------------------


def _pending(s, side) -> list:
    return [
        u for u in s.units.values()
        if u.side == side and not u.activated and not u.out_of_action
    ]


def _step_activation(s, decision, ev, rng, rules) -> None:
    if s.activating_unit is None and not any(_pending(s, sd) for sd in s.sides()):
        _advance_phase(s, ev, rules)
        return
    if s.activating_unit is None and not _pending(s, s.active_side):
        _next_activator(s)

    side = s.active_side
    if s.activating_unit is None:
        _start_unit_activation(s, decision, side, ev, rng, rules)
        return

    u = s.units[s.activating_unit]
    if isinstance(decision, EndActivation):
        _finish_activation(s, u, ev, rng, rules)
        return
    if not is_action(decision):
        raise IllegalAction("expected an action or EndActivation")
    if s.actions_taken >= rules.game["actions_per_activation"]:
        raise IllegalAction("no actions remaining this activation")

    resolve._apply_action(s, decision, rules, rng, ev)
    s.actions_taken += 1
    bolster = getattr(decision, "bolster", None)
    if bolster and bolster != "reboot":
        s.bolstered_count += 1

    if u.out_of_action:
        _finish_activation(s, u, ev, rng, rules, died=True)
    elif s.actions_taken >= rules.game["actions_per_activation"]:
        _finish_activation(s, u, ev, rng, rules)


def _start_unit_activation(s, decision, side, ev, rng, rules) -> None:
    if isinstance(decision, Pass):
        if s.pass_tokens.get(side, 0) <= 0:
            raise IllegalAction("no pass tokens available")
        s.pass_tokens[side] -= 1
        emit(s, ev, "pass", side=side)
        _next_activator(s)
        _maybe_end_activation(s, ev, rules)
        return
    if not isinstance(decision, ActivateUnit):
        raise IllegalAction("expected ActivateUnit or Pass")
    u = s.units.get(decision.unit_id)
    if u is None or u.side != side or u.activated or u.out_of_action:
        raise IllegalAction("cannot activate that unit")
    s.activating_unit = u.id
    s.actions_taken = 0
    s.bolstered_count = 0
    emit(s, ev, "activation_start", unit=u.id, side=side)


def _finish_activation(s, u, ev, rng, rules, died: bool = False) -> None:
    if not died:
        heat = (1 if s.actions_taken >= rules.game["actions_per_activation"] else 0)
        heat += s.bolstered_count
        if heat > 0:
            resolve._gain_heat(s, u, heat, "activation", ev, rng, rules)
    u.activated = True
    for w in u.weapons:
        w.used_this_turn = False
    for key in ("purged_this_turn", "moved_this_turn", "heavy_fired"):
        u.statuses.pop(key, None)
    emit(s, ev, "activation_end", unit=u.id, died=died)
    s.activating_unit = None
    s.actions_taken = 0
    s.bolstered_count = 0
    if not _pending(s, u.side) and s.round_first_finisher is None:
        s.round_first_finisher = u.side
        emit(s, ev, "side_finished", side=u.side)
    _next_activator(s)
    _maybe_end_activation(s, ev, rules)


def _next_activator(s) -> None:
    seq = [sd for sd in s.initiative if sd != s.active_side] + [s.active_side]
    for sd in seq:
        if _pending(s, sd):
            s.active_side = sd
            return


def _maybe_end_activation(s, ev, rules) -> None:
    if not any(_pending(s, sd) for sd in s.sides()):
        _advance_phase(s, ev, rules)


# --------------------------------------------------------------------------
# heat phase
# --------------------------------------------------------------------------


def _run_heat_phase(s, ev, rng, rules) -> None:
    for sd in s.initiative:
        members = [u for u in s.units.values() if u.side == sd and not u.out_of_action]
        for u in members:
            roll = rng.d6()
            emit(s, ev, "dice_roll", unit=u.id, purpose="heat_check", notation="d6",
                 results=[roll], total=roll)
            table = rules.heat_check_table(u.heat_check_table)
            gain = table.get(roll, 0)
            if gain:
                resolve._gain_heat(s, u, gain, "heat_check", ev, rng, rules)


# --------------------------------------------------------------------------
# victory
# --------------------------------------------------------------------------


def _check_victory(s, ev, rules) -> None:
    if s.winner is not None:
        return
    live = {sd: len(s.live_units(sd)) for sd in s.sides()}
    alive = [sd for sd, n in live.items() if n > 0]
    if len(alive) <= 1:
        _finish_game(s, ev, alive[0] if alive else -1, "annihilation", live)
        return
    if s.round > rules.game["rounds"]:
        if s.mission == "warzone":
            best = max(live.values())
            top = [sd for sd, n in live.items() if n == best]
            winner = top[0] if len(top) == 1 else -1
        else:
            winner = -1
        _finish_game(s, ev, winner, "round_limit", live)


def _finish_game(s, ev, winner, reason, live) -> None:
    s.winner = winner
    s.end_reason = reason
    s.phase = "done"
    s.activating_unit = None
    emit(s, ev, "game_over", winner=winner, reason=reason,
         survivors={str(k): v for k, v in live.items()})
