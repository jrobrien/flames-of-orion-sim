"""Bot policies: callables mapping (GameState, unit_id) -> a decision for the engine.

Imports ``foosim.engine`` only. Keep a stable, simple baseline policy for
regression testing and iterate smarter policies alongside it (do not mutate the
baseline, or historical analysis runs stop being comparable).
"""
