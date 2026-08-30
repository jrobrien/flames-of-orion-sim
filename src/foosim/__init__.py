"""foosim - a rules-testing sandbox for the tabletop mech game Flames of Orion.

Layer rules (enforced by convention + tests, see PLAN.md section 2):

    engine/  pure, deterministic, STDLIB ONLY. portable to another language.
    ai/      bot policies. imports engine only.
    sim/     run / replay / generate / analyze. imports engine + ai. may use numpy/pandas.
    ui/      imgui-bundle front-end. the only importer of imgui_bundle. nothing imports it.
"""

__version__ = "0.0.1"
