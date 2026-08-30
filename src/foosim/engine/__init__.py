"""Pure, deterministic Flames of Orion rules engine.

HARD RULE: nothing in ``foosim.engine`` may import from ``foosim.ui``,
``imgui_bundle``, ``numpy``, ``pandas``, or any rendering / IO library. The engine
is plain dataclasses + pure functions so it can be ported to another runtime
(e.g. a Godot / C# front-end) by mechanical translation.

Core contract:

    apply(state, action, rng, rules) -> (new_state, list[Event])

``apply`` never mutates its inputs and emits every dice roll and sub-decision as a
structured Event. See PLAN.md and RULES.md.
"""
