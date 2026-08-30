"""Headless drivers: run whole games, record/replay them, generate units, batch them.

Imports ``foosim.engine`` and ``foosim.ai``. May use numpy / pandas (the
``analysis`` extra). Must not import ``foosim.ui``.

A battle is fully described by ``(seed, setup, decisions)``; snapshots are derived
by re-running, not stored. Re-running an old Replay against an edited
``data/rules.toml`` is the A/B experiment.
"""
