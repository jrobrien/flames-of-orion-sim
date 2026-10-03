"""Export the rules data the web sheet generator needs to docs/data.js.

The web app (docs/index.html + app.js) is a standalone port and is allowed to drift
from the Python generator; this script just seeds/refreshes its data tables from
data/rules.toml (prices, perks, frames, call signs) and the sheet's description text.

    uv run python scripts/export_web_data.py
"""

from __future__ import annotations

import json
from pathlib import Path

from foosim.engine.rules import load
from foosim.sim import sheet

OUT = Path(__file__).resolve().parent.parent / "docs" / "data.js"


def main() -> None:
    raw = load().raw

    def weapon(w: dict) -> dict:
        return {
            "id": w["id"], "name": w["name"], "damage": str(w["damage"]),
            "slots": int(w.get("platform_slots", 1)), "cost": int(w["cost"]),
            "text": sheet._WEAPON_TEXT.get(w["id"], ""),
            "noAmmo": "no_specialty_ammo" in w.get("special", []),
        }

    data = {
        "mechCost": raw["game"]["mech_cost"],
        "frames": {k: raw["frames"][k] for k in ("light", "medium", "heavy")},
        "ranged": [weapon(w) for w in sorted(raw["ranged_weapons"], key=lambda w: w["roll"])],
        "melee": [weapon(w) for w in sorted(raw["melee_weapons"], key=lambda w: w["roll"])],
        "ammo": [
            {"id": a["id"], "name": a["name"], "cost": a["cost"],
             "text": sheet._AMMO_TEXT.get(a["id"], "")}
            for a in sorted(raw["ammo"], key=lambda a: a["roll"])
        ],
        "upgrades": [
            {"id": u["id"], "name": u["name"], "cost": u["cost"],
             "stackable": bool(u.get("stackable")), "effect": u.get("effect", {}),
             "text": sheet._UPGRADE_TEXT.get(u["id"], "")}
            for u in sorted(raw["upgrades"], key=lambda u: u["roll"])
        ],
        "perks": raw["perks"],
        "callSignA": raw["call_sign"]["table_a"],
        "callSignB": raw["call_sign"]["table_b"],
    }
    OUT.write_text("window.FOO_DATA = " + json.dumps(data, indent=1) + ";\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
