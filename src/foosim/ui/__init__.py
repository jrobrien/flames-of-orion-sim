"""imgui-bundle desktop front-end. The ONLY place ``imgui_bundle`` may be imported.

Depends on everything else; nothing else depends on it. The UI never mutates
GameState directly - it builds a decision, calls the engine, and re-renders from
the returned ``(state, events)``.
"""
