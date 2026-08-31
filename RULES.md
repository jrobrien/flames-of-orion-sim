# Flames of Orion — Combat Rules Reference (implementation spec)

> **Status:** distilled from the *Free Edition, v10.10* for the purpose of building
> a rules-testing simulator. This document is a **functional specification written
> from scratch** — it contains no text, art, or layout from the rulebook. Game
> rules and numbers are not protected by copyright; the rulebook's *expression* is.
>
> **Flames of Orion is © 2025 Stephen Hupfer.** This project is an unofficial
> fan-made playtesting tool. Buy the game: <https://www.underthedice.com>
>
> Purpose of this file: be the thing the engine and the developer re-read instead
> of the 49 MB PDF. When the code and this file disagree, fix one of them.

Page numbers `(p.NN)` refer to the Free Edition PDF for traceability only.

---

## 0. Adaptation decisions (digital / hex)

The tabletop game is measure-and-move in inches with no grid. This sim uses a
**pointy-top axial hex grid**. Decisions where the rulebook is silent or assumes a
tape measure are marked **[ADAPT]** and are all tunable in `data/rules.toml`.

| Tabletop concept | Sim mapping |
|---|---|
| 1 inch | `meta.hex_per_inch` hexes (default **1**). All ranges/speeds stored in inches, converted on use. |
| Distance between models | hex distance (cube distance) |
| "within 1 inch" (Engaged, Ram, pick-up, pushes) | hex distance ≤ 1 (adjacent) |
| "within 2 / 3 inches" | hex distance ≤ 2 / ≤ 3 |
| Long Range (`> 10"`) | hex distance `> to_hit.long_range_inches` |
| Speed `S` | move up to `S` hexes |
| Explosion radius = current HEAT | that many hexes |
| Terrain polygons | **[ADAPT]** snapped to whole hexes, each tagged `blocking` / `cover` / `destructible` (any combination). A polygon-accurate continuous mode is a later option (see PLAN "porting to Godot"). |
| Line of sight & cover | **[ADAPT]** pluggable — see [§5.1](#51-line-of-sight--cover-model-sim). Default is a multi-ray sample between the two hexes (LOS if *any* sightline is clear; cover if *some* sightline is obscured), not a single centre-to-centre line. |
| Facing | tracked as 0–5 (hex directions) for future rules / graphics. **No combat effect** in v1 (LOS is 360°). |
| Elevation / vertical move / gaps > 2" / falling | **[ADAPT]** v1 maps are flat; `elevation:int` per hex is in the schema but ignored by movement. Falling / vertical cost = TODO (v2). |
| Bolstered attacks "resolve at once" | modelled as: roll every sub-attack, collect damage, then apply saves/effects; cross-attack bonuses apply only after all sub-attacks (p.58 FAQ). |
| One model per hex | enforced. Move *through* friendly-occupied hexes allowed; may not end there; may not move through enemy-occupied hexes. |
| Mech moving over Infantry (d6 1–3 → flatten) | **[ADAPT]** checked per enemy Infantry hex entered during a Move. |

---

## 1. Unit stats (p.10)

| Stat | Meaning | Engine notes |
|---|---|---|
| **HP** — Hull Points | damage capacity. 0 HP → Explode Check → Out of Action. | int, current & max |
| **AR** — Armor | "X+"; per point of incoming damage roll d6, `≥ AR` ignores that point. | stored as the number X |
| **CS** — Combat Skill | "X+"; roll d6 `≥ CS` to hit with Ranged/Melee. Also the target number for confirming Catastrophic Damage. | stored as X |
| **S** — Speed | move distance in inches (→ hexes). | int |
| **HL** — Heat Limit | reach or exceed → immediately set to 0 HP. | int |
| **PF** — Platforms | equipment slots. Start 4, max 8. Two kinds: Weapon platforms (Ranged/Melee) and Upgrade platforms. | int |

d66: roll a d6 for the tens digit and a d6 for the ones → 11–66.

---

## 2. Unit profiles

### Mech frames (p.11, p.21) — cost 50,000¢

| Frame (d6) | S | CS | AR | HP | HL | PF |
|---|---|---|---|---|---|---|
| Light (1–2) | 7 | 4+ | 6+ | 4 | 12 | 3 |
| Medium (3–4) *(baseline)* | 6 | 4+ | 6+ | 6 | 10 | 4 |
| Heavy (5–6) | 5 | 4+ | 5+ | 7 | 9 | 5 |

### Ground Forces (p.30) — may replace **1 Mech with 2 Ground Forces**; min 2 Mechs in a unit; no Melee weapons

| Type | S | CS | AR | HP | HL | PF | Cost | Notes |
|---|---|---|---|---|---|---|---|---|
| Land Vehicle | 5 | 4+ | 6+ | 4 | 7 | 3 | 30,000¢ | explodes normally |
| Infantry | 4 | 5+ | 6+ | 2 | 5 | 2 | 10,000¢ | up to **3 per Mech slot**; may not Ram; gains HEAT but **does not Explode** (panics instead); when an enemy Mech/vehicle moves over, d6 `1–3` → Out of Action; may Garrison destructible terrain |
| Aircraft | 8 | 4+ | 6+ | 2 | 8 | 2 | 25,000¢ | ignores terrain on Move actions |

---

## 3. Game structure (p.12)

A game is **5 Rounds**. Each Round has 3 Phases in order:

1. **Initiative Phase** — every player rolls d6; highest goes first, then next, etc.
   Ties re-roll. A player who *finished* activating all their models first last
   Round adds **+1** to this roll.
2. **Activation Phase** — players alternate; on your turn pick one un-activated
   model and give it **up to 2 Actions**, then place its Activation token. When a
   player has no models left, the others keep going in order.
   - *Outnumbered (p.34):* the player with fewer models than the largest force
     gets Pass Activation tokens equal to the difference; may discard one instead
     of activating, passing to the next player. Discard all leftover Pass tokens
     when the largest force loses a model.
   - *Retreat/Surrender (p.12):* at the start of your turn you may concede.
3. **HEAT Phase** — in Initiative order, players alternate making one HEAT Check
   per model (see §7), then discard that model's Activation token.

Game also ends early if a side has no models (or all remaining concede).
Mission victory is evaluated at end of Round 5 (see §12).

> **Sim note — phases are data, not code.** `engine/phases.py` runs the phase
> sequence from `data/rules.toml [game] phase_order`. Rule experiments that add or
> reorder phases (e.g. a bonus end-of-round close-combat phase:
> `["initiative", "activation", "bonus_melee", "heat"]`) are a config edit plus a
> phase handler + an AI branch — not a framework change. Replay records are
> `{round, phase, side, unit, action}`, so extra phases serialize for free.

---

## 4. Actions (p.14–15)

Five base actions: **Move, Ranged Attack, Melee Attack, Disengage, Purge HEAT.**
Order is free; the same action may be taken twice.

**HEAT from activation** (applied *after* all actions resolve, p.15):
`+1` if a 2nd action was taken, `+1` for **each** Bolstered action taken.
(Plus any weapon-specific HEAT, e.g. Rail Weapon `+1` on use.)

A **Bolstered** action replaces a standard action of the same type and adds the
extra HEAT above. You choose one sub-mode:

### MOVE
Move up to `S` hexes. Pivot freely, any number of times, at any point. Move
through friendly-occupied hexes (not enemy). One model per hex; may not end in an
occupied hex.
- **Bolstered — Charge:** move up to `S`, then a free Melee Attack (or Ram a model
  within 1").
- **Bolstered — Run:** move up to `S`, then up to **+3"** more.
- **Bolstered — Snap Shot:** move up to `S`; may pause once to make a **basic
  Ranged Attack at −1 CS**, then finish the move.

### RANGED ATTACK
Pick a weapon not already fired this turn. Roll d6 `≥ CS` to hit → weapon damage.
Most ranged weapons have unlimited range. **May not be used while Engaged** (§6).
- **Bolstered — Unleash Hell:** fire *every* ranged weapon not yet fired this
  turn; roll each separately.
- **Bolstered — Focused Fire:** one weapon not yet fired, **+1 CS**.

### MELEE ATTACK
Pick a melee weapon not already used this turn. Roll d6 `≥ CS` to hit → weapon
damage. Requires being adjacent (or within the weapon's reach, e.g. Cable Whip 3").
- **Bolstered — Fury:** attack with *all* melee weapons not yet used this turn.
- **Bolstered — Focused Strike:** one melee weapon not yet used, **+1 CS**.
- **Bolstered — Ram:** deal `1d3` to yourself and `1d3` to a model within 1".

### DISENGAGE
Move out of combat at **½ `S`** (round down). The enemy you were Engaged with
makes a **free Melee Attack** (melee weapon) against you.
- **Bolstered — Dodge:** as Disengage but **no free enemy attack**.

### PURGE HEAT
Remove `1d3` HEAT and gain **Position Compromised** (§5). Once per turn. This
action generates **no** HEAT.
- **Bolstered — Reboot:** remove `2d3` HEAT. Must be the model's **only** action
  this turn. Generates no HEAT and **no** Position Compromised.

---

## 5. Combat modifiers & statuses

- **Line of Sight (p.16):** any part of attacker to any part of target, unbroken.
  360°. See §0 for the hex algorithm.
- **Long Range (p.16):** target at `> 10"` → **−1 CS** on the hit roll. The Rail
  Weapon checks this per hit roll. Negated by *Long Range Systems* weapon,
  *Long Range Targeting* upgrade, or *A.I. Missile System*.
- **Cover (p.16, p.20 / QR p.61):** partial obstruction by terrain **or another
  model** → **+1 to each of the target's AR save rolls** for that attack (i.e. the
  natural roll it needs drops by 1). If the attack misses, it hits the obscuring
  model/terrain (**[ADAPT]** v2). *Large Missile Battery* splash targets only get
  cover if cover lies between the original target and them (p.58).
- **Armor Penetration (AP) (p.29 / QR p.61):** **−1 to each of the target's AR
  save rolls** for that attack (the natural roll it needs rises by 1). Multiple
  sources **stack**. A **natural 6 always saves** regardless of AP.

> **Sign convention (sim):** all "CS"/"AR" numbers are stored as the d6 **target
> number** ("4+" → `4`). A modifier that makes the roll *harder* is **positive**.
> Cover/AP are modelled as roll modifiers per QR p.61, not "AR value" changes:
> `save_tn = AR − cover + AP`, save if `d6 ≥ save_tn` (or natural 6).
- **Engaged (p.16):** within 1" of an enemy → **cannot Move or Ranged Attack**;
  use Disengage to leave. Melee is fine.
- **Position Compromised (p.15):** any model targeting a PC-affected model gets
  **+1 CS** on its next attack against it; removed after that attack resolves.
  **Does not stack** (p.58). Gained from Purge HEAT, *Up-Link*, Tracer Rounds.
- **Active Camo (from *Camouflage* upgrade):** enemies making **Ranged** attacks
  vs this model get **−1 CS**. Lasts until the camo'd model's next action.

### 5.1 Line of sight & cover model (sim)

On the tabletop, LOS is *"any part of the model to any part of the target,"*
eyeballed over 3D terrain, with real height levels (a model on a building sees
over things a ground model can't). Single centre-to-centre hex LOS is too strict
and plays wrong. `engine/visibility.py` implements this as a **pluggable
strategy**, selected by `data/rules.toml [visibility] mode`:

| mode | how | use |
|---|---|---|
| **`multiray_2d`** *(default)* | sample a spread of points across the attacker hex and the target hex (`sample_corner_fraction` controls the spread); trace every sightline. **LOS** = at least one line avoids `blocking` terrain. **Cover** = at least one line clips `blocking`/`cover` terrain or a third model (target partially obscured). | day-to-day; approximates "any part of the model" + "partially obscured → cover" without needing elevation data |
| **`strict_center`** | one centre-to-centre line | comparison / debugging / other-game feel |
| **`center_25d`** | centre line as a 3D beam from observer eye (`eye_height` above its hex column) to the top of the target; blocked when an intervening column (`Board.column_height` = ground elevation + structure height) rises above the beam; grazing an obstacle → cover | **experimental.** Needs elevation + structure-height data on maps (schema lands M2; real maps + validation later). This is the path to "high ground sees more". |

`resolve.py` only ever calls `visibility.line_of_sight(board, a, b, cfg)` and reads
`.los` / `.cover` / `.blocked_by`. Weapons that ignore LOS (A.I. Missile System)
or cover just discard the field. Tuning `sample_corner_fraction` up makes units
"see around corners" more; this is a deliberate knob for playtesting.

**Still open:** exact `center_25d` semantics, where map elevation/structure-height
data comes from, and hand-validation against a few tabletop situations. Tracked in
§18 and `PLAN.md §10`.

---

## 6. Attack resolution (canonical order)

```
RANGED / MELEE ATTACK against target T with weapon W:

 1. Validate: W not used this turn; (ranged) attacker not Engaged;
    LOS exists unless W ignores LOS; in reach (melee / limited-range weapons).

 2. Effective hit target number = attacker.CS, then apply, as +N harder / -N easier:
       +1 harder : Long Range and not ignored
       +1 harder : Snap Shot bolstered move shot
       -1 easier : Focused Fire / Focused Strike
       -1 easier : Targeting System upgrade
       -1 easier : Position Compromised applies to T
       -1 easier : Thermal Imaging upgrade and T.heat >= 5
       +1 harder : T has Active Camo (ranged only)
       (Energy Sword: also crit on natural 5)

 3. Roll d6 (once per sub-attack):
       1              -> MISS (always)
       6              -> HIT + CRITICAL (always)
       >= eff. target -> HIT
       else           -> MISS

 4. Flame Thrower: on HIT, add 1d2 to T.heat now (before saves, p.58).

 5. Compute damage:
       base = roll W.damage  (fixed, or d3 / d2 as specified)
       + ammo / weapon damage mods (Hellfire +1, Lance +2 if moved, ...)
       if CRITICAL: damage += 1
                    + 1 if attacker has Sensor Array
                    (Counter Missiles on T: negate the crit's extra damage, ranged)

 6. If CRITICAL: roll d6; if >= attacker.CS  -> CATASTROPHIC (see §8)
       roll 2d6 on the table; that result's inherent +1 damage is added;
       apply the effect (lasts until end of game).

 7. Armor saves:  save_tn = T.AR - (1 if cover) + (AP sources)
       for each point of damage: roll d6; (>= save_tn OR natural 6) -> ignored;
       else T.HP -= 1
       (Reactive Armor: ignore the first 1 point this game.
        AR is rolled once per point; AR "always saves on a natural 6" per QR p.60.)

 8. If T.HP <= 0: Explode Check (§7) -> Out of Action.

 9. Mark W used this turn.
```

**Bolstered attacks:** run steps 1–8 for each sub-attack, then apply
end-of-activation HEAT. Cross-attack benefits do not apply mid-sequence (p.58).

---

## 7. HEAT, overheat, Explode (p.18)

- **HEAT sources:** 2nd action `+1`; each Bolstered action `+1`; Rail Weapon `+1`
  on use; some catastrophic results; Solar Flare mission, etc. Flame Thrower adds
  HEAT to the *target*, not the firer.
- **Applied after actions resolve.** Then check overheat.
- **Overheat:** if `HEAT >= HL` at any point after a HEAT gain → **HP set to 0** →
  Explode Check.
- **HEAT Check (HEAT Phase, per model):** roll d6 →

  | d6 | 1 | 2 | 3 | 4 | 5 | 6 |
  |---|---|---|---|---|---|---|
  | HEAT gained (default) | +2 | +1 | +1 | +1 | 0 | 0 |
  | with *Heat Sink* upgrade | +2 | +1 | 0 | 0 | 0 | 0 |

  Then re-check overheat.

- **Explode Check (on reaching 0 HP):** roll d6.
  - `1–2` → just Out of Action.
  - `3–6` → **Explode**: damage `= floor(HEAT / 2)`, min 1; radius `= HEAT` hexes.
    Every model within radius takes that damage (AR saves as normal); destructible
    terrain within radius takes damage; **blocking terrain blocks** the explosion.
    Kills caused this way credit the exploding unit (p.58). *Nuclear Core* upgrade:
    explode as if HEAT 10. Then Out of Action.
- Infantry that reach HL are removed (panic), **no explosion**.

---

## 8. Critical & Catastrophic Damage (p.16–17)

- Natural **6** on a hit roll = Critical: **+1 damage**, then roll to confirm
  Catastrophic.
- **Confirm:** d6 `≥ attacker.CS` → Catastrophic. Roll **2d6**:

  | 2d6 | Result | Effect (until end of game) |
  |---|---|---|
  | 2 | Ammo Explodes | `+1d3` extra damage; special ammo on the weapon is lost |
  | 3 | Platform Disabled | a random platform (weapon/upgrade) is disabled |
  | 4 | Targeting System Disrupted | −1 CS |
  | 5 | Cracked Reactor Core | HL −1 |
  | 6 | Ricochet | 1 damage to a random model within 3" |
  | 7 | Heavy Fire | +1 damage |
  | 8 | Leaking Hydraulics | −1 S |
  | 9 | Armor Compromised | all attackers vs this model gain AP |
  | 10 | Oil Burn | HL −1 |
  | 11 | Weapon Disabled | a random weapon is disabled |
  | 12 | Cockpit Fire | model set to 0 HP (→ Explode Check) |

  The table's damage entries are **in addition to** the crit's +1.

---

## 9. Terrain (p.20)

- Declared before the game as **Destructible** or **Indestructible**. Blocks LOS.
- **Destructible:** mark when damaged. Destroyed when it takes a 2nd hit the same
  turn **or** `≥ 3` damage in one action. On destruction: removed + **1 damage to
  all models within 2"**. A Mech that moves onto destructible terrain: d6 `1–2` →
  it's destroyed, remove it and apply fall damage to the Mech.
- **Indestructible:** cannot be destroyed. **Rail Weapons cannot fire through it.**
- **Cover:** see §5.
- Explosions: destructible terrain takes explosion damage as normal; blocking
  terrain stops explosions.

---

## 10. Ranged weapons (p.28) — rulebook d8

| d8 | Name | Dmg | PF | Notes |
|---|---|---|---|---|
| 1 | Flame Thrower | 1 | 1 | max range 10"; on hit, target +1d2 HEAT; **no specialty ammo** |
| 2 | Light Weapon | 1 | 1 | — |
| 3 | Medium Weapon | 2 | 1 | — |
| 4 | Heavy Weapon | 4 | 2 | if fired this turn, equipped model may only Move at ½ speed |
| 5 | Rail Weapon | d3 | 1 | pick a point; line from firer to point; one attack vs **each** model & destructible terrain on the line (**hits friendlies**); `+1` HEAT on use; needs LOS only to the initial target/terrain; blocked by indestructible terrain |
| 6 | A.I. Missile System | 1 | 1 | max range 20"; **ignores LOS**; ignores cover bonus |
| 7 | Long Range Systems | 2 | 1 | **AP**; ignores the −1 Long Range penalty |
| 8 | Large Missile Battery | d2 | 1 | on a target, also roll to hit vs all models & terrain within 2" of it (splash) |

## 11. Melee weapons (p.28) — rulebook d8

| d8 | Name | Dmg | PF | Notes |
|---|---|---|---|---|
| 1 | Basic Combat Attachment | 1 | 1 | — |
| 2 | Close Combat Weapon | 2 | 1 | — |
| 3 | Cable Whip | 2 | 1 | reach 3"; Engagement range 3" (treats enemies within 3" as Engaged for this weapon) |
| 4 | Lance | 1 | 1 | if the model made a Move action this turn: `+2` damage and gains AP for this action |
| 5 | Power Weapon | 2 | 1 | **AP**; on a hit roll of `1`, the power core burns out → loses AP for the rest of the match |
| 6 | Electric Field | 1 | 1 | attack **all other models within 2"**; each hit takes 1 dmg and is pushed 1" |
| 7 | Piston Gauntlet | 2 | 1 | on hit, may move the target 1" directly away |
| 8 | Energy Sword | 2 | 1 | Critical on hit rolls of `5+`; on a hit roll of `1`, fusion core burns out → becomes a 1-damage melee weapon for the rest of the game |

## 12. Ammo (p.29) — rulebook d6

Optional, no PF cost. Bought per weapon (buy twice to cover two weapons). At end
of game, per ammo: d6 `1–3` → depleted, must re-buy to keep using.

| d6 | Name | Effect |
|---|---|---|
| 1 | Flechette Rounds | weapon gains **AP** |
| 2 | Hellfire Rounds | `+1` damage |
| 3 | EMF Rounds | damaged model `−2 S` until end of its next activation |
| 4 | Concussive Rounds | target pushed 2" directly away; if it hits a model/terrain, 1 dmg to each |
| 5 | Rapid Fire Rounds | on a hit roll of `6`, apply crit as normal, then may roll another ranged attack with this weapon |
| 6 | Tracer Rounds | target gains Position Compromised; **firer also** gains Position Compromised |

## 13. Upgrade platforms (p.27) — rulebook d20. `*` = may be taken multiple times.

| d20 | Name | Effect |
|---|---|---|
| 1 | Armor Mk I | AR becomes 5+ |
| 2 | Armor Mk II | AR becomes 4+ |
| 3 | Reactive Armor | ignore the first 1 point of damage this model takes (per game) |
| 4 | VTOL | ignore terrain when making a Move action |
| 5 | Thrusters* | `+1 S` |
| 6 | Heat Sink | HEAT Check becomes 1→+2, 2→+1, 3–6→0 |
| 7 | Sensor Array | Critical Hits deal an extra `+1` damage |
| 8 | Heavy Plating* | `+1 HP` |
| 9 | Core Stabilizers* | `+2 HL` |
| 10 | Extra Platforms* | `+1 PF` (does **not** consume a PF slot) |
| 11 | Self Destruct | on your turn with `HEAT ≥ 7`, may take a Self Destruct action → model explodes |
| 12 | Camouflage | action → Active Camo until this model's next action; enemy ranged attacks vs it `−1 CS` |
| 13 | Nuclear Core | when this Mech explodes, it explodes as if at HEAT 10 |
| 14 | Targeting System | `+1 CS` on this model's rolls |
| 15 | Up-Link | spend an action to target an enemy in LOS → it gains Position Compromised |
| 16 | Long Range Targeting | ignore the Long Range rule for this model's Ranged actions |
| 17 | Defense Array | when an enemy moves within 1", d6 `4+` → it is placed just outside 1" |
| 18 | Thermal Imaging | when targeting a model with `HEAT ≥ 5`, `+1 CS` |
| 19 | Counter Missiles | when hit by a ranged Critical, negate the crit's extra damage |
| 20 | Virus Program | once per game, on activating this model, infect an enemy: it may take only 1 action that turn, not bolstered |

---

## 14. Building a Combat Unit (p.22–31)

- **4 Mechs** typical, **minimum 2**. Each Mech 50,000¢. May swap 1 Mech for 2
  Ground Forces.
- **Quick Play (p.23):** 4 free Mechs + 25,000¢. For each Mech, for each of its 4
  PF slots, roll on the appropriate Black Market table (Ranged d8 / Melee d8 /
  Upgrade d20) and gain it free. May spend 10,000¢ to re-roll one PF result.
- **Veteran (p.23):** 4 free Mechs + 150,000¢, choose a faction, buy freely.
- **Random generation for the sim** (`foosim.sim.generate`):
  - Frame: d6 → Light/Medium/Heavy (see §2).
  - For each PF slot: choose/roll table (weapon vs upgrade), roll on it, pay slot
    cost (weapons cost their PF; Heavy Weapon = 2 PF; Extra Platforms adds slots).
  - Optionally assign ammo to ranged weapons.
  - Call sign: two d66 rolls on tables A and B (`data/rules.toml [call_sign]`).

### Factions (Veteran/campaign only, p.24–25)

| Faction | Bonus |
|---|---|
| Mercs — *No More Heroes* | free random Weapon **or** Upgrade + free random Ammo |
| Mega Corps — *Forced Labor* | free Infantry w/ Light Weapon; doesn't count vs unit size limit |
| Noble Houses — *Generous Tithing* | `+30,000¢` |
| The Lost & The Damned — *Strength Through Suffering* | when a model is destroyed by an enemy, give a surviving model `+1 CS` on its next activation |

---

## 15. Missions & victory (p.36–38)

Evaluated at end of Round 5 unless noted. Implement as pluggable objects with
`winner(state) -> side | None`.

| # | Name | Objective / victory |
|---|---|---|
| 1 | **Warzone** | most models still standing at end of R5 wins |
| 2 | Recovery | carry the central Cargo token at end of R5 (Cargo pickup = free action; carrying it adds `+1` HEAT whenever the carrier takes a 2nd/bolstered action) |
| 3 | Scavenge | most Loot Tokens by end of R5 (5 Ruins each; search adjacent Ruin, d6 table) |
| 4 | Burned to a Crisp | get models into shelters + hold Loot Tokens; **Solar Flare**: end of each round, models that gained HEAT on their HEAT Check take `+1` HEAT and 1 damage |
| 5 | Hold the Line | Attacker/Defender + Drop Ship marker; Attacker wins by ending a round with more models within 3" of the Drop Ship, or wiping the Defender; Defender wins by surviving 5 rounds |
| 6 | Noble Fight | last player with a model on the board |

**v1 implements:** Warzone + pure annihilation. Others are M8.

### Special Objectives (secret, optional, p.35) — reward = 1 Salvage roll

Systems Hot (gain 10 HEAT then Explode with a Mech) · Nothing Our Way (destroy 2
terrain) · Death by a Thousand Cuts (deal ≥1 dmg to every enemy model) · Deadly
Grudge (land the killing blow on ≥2 enemy models via an Attack action) · Fill the
Coffers (most Loot Tokens) · Never Let Them See You Burn (Purge ≥6 total HEAT) ·
Cool, Calm & Collected (finish with ≥1 Mech at ≤3 HEAT) · Last One Standing (end
with only a single Mech from your unit).

---

## 16. Setup (p.34)

1. Pick/roll a Mission; decide on Special Objectives.
2. Alternate placing Destructible/Indestructible terrain (aim for LOS blockers
   spread across the board).
3. Deployment: roll off; winner picks a board edge/corner, opponent takes the
   opposite. Alternate placing models within 3" of your edge (or 8" of a corner).
4. Outnumbered player gets Pass Activation tokens (§3).

---

## 17. Edge cases / FAQ (p.58) folded into the rules above

- Bolstered attacks resolve simultaneously; benefits apply after (see §6).
- Flame Thrower HEAT: after a successful hit roll, before AR saves.
- Ground Forces Explode (Infantry do not).
- Explode-caused kills count for the exploding unit.
- Large Missile Battery splash: cover only if it sits between original and splash
  target.
- Rail Weapon checks Long Range per hit roll; needs LOS only to the initial
  target/terrain; cannot pass through indestructible terrain.
- Cannot fire ranged weapons while Engaged — Disengage first.
- Position Compromised does not stack.
- AR "always saves on a natural 6" regardless of AP (QR p.60).
- A natural `1` on a hit roll always misses; natural `6` always crits.
- Falling deals 1 damage.

---

## 18. Open questions / TODO for the sim

- **[ADAPT]** LOS + cover — approach decided (§5.1: pluggable, default
  `multiray_2d`). Remaining: nail down `center_25d` semantics, decide where map
  elevation / structure-height data lives (M2 schema), hand-validate the default
  against a handful of real tabletop situations, and tune `sample_corner_fraction`.
- **[ADAPT]** "hits the obscuring model/terrain on a miss" — defer to v2.
- **[ADAPT]** elevation, vertical move cost, gaps, VTOL gap-ignore, fall damage.
- Cable Whip full text (Engagement interaction, forced move) — approximate now,
  revisit with the paid edition if acquired.
- Whip-cable + Disengage interaction (p.58) is fiddly — note in code.
- Multi-player (3+) — out of scope; 2 sides only.
- Campaign layer (scars, salvage, credits, bunkers) — explicitly out of scope.
