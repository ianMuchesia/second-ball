# Pressure, risk, options and "bad_situation"

Status: **spec only**. No metric code until Phase 2.
Red zone: thresholds are Ian's decisions. Agents never change them.

Every number marked **TUNABLE** is owned by **Ian**. Change it here first,
then in code, then re-run evals.

## Conventions

Taken from the contracts (`core/contracts/event.py`):

- Pitch 105 × 68 m. SPADL convention: the acting team attacks towards x = 105,
  so its **own goal is at (0, 34)**.
- `facing_deg`: 0° points along +x, 90° along +y, anticlockwise, range [0, 360).
- All inputs come from one `MatchEvent`: the ball carrier is `player_id` at
  (`start_x`, `start_y`); other players come from `freeze_frame`.

## pressure (0–1)

How hard the ball carrier is being pressed.

- Count opponents within **5 m** of the ball carrier. **TUNABLE** (owner: Ian)
- Each opponent adds weight by closeness: closer means more weight.
- An opponent **in front** of the carrier or **goal-side** of the carrier
  counts **double** (weight × 2). **TUNABLE** (owner: Ian)
- Result is in 0–1.
- `under_pressure = pressure >= 0.5`. **TUNABLE** (owner: Ian)

## risk (0–1)

How costly losing the ball here would be.

- Based on the ball's distance to the carrier's own goal.
- High inside the own penalty box (x ≤ 16.5, 13.84 ≤ y ≤ 54.16).
- About 0 in the final third (x ≥ 70).
- Shape of the curve in between: **TUNABLE** (owner: Ian)

## options (int)

How many safe passes the carrier has.

- Count teammates whose passing lane has **no opponent within 2 m** of it.
  **TUNABLE** (owner: Ian)

## Moment: `bad_situation`

Fires when all four are true:

| Condition | Threshold |
|---|---|
| pressure | ≥ **0.5** (TUNABLE, owner: Ian) |
| risk | ≥ **0.6** (TUNABLE, owner: Ian) |
| options | ≤ **1** (TUNABLE, owner: Ian) |
| facing own goal | carrier's `facing_deg` points towards (0, 34), tolerance TUNABLE (owner: Ian) |

Evidence: the moment's `evidence_event_ids` must include the event that
triggered it.

## Open questions (Ian to decide before Phase 2)

1. **Closeness weight:** what shape? (e.g. linear `1 − d/5`, or something steeper)
2. **Scaling to 0–1:** what total counts as full pressure (1.0)? Cap or squash?
3. **"In front":** in front of the carrier's facing direction, or towards the
   opponent's goal? **"Goal-side":** between the carrier and their own goal
   (opponent x < carrier x)? If an opponent is both, does it count ×2 or ×4?
4. **Risk curve:** linear in distance, stepped by zone, or something else? What
   value exactly at the box edge and at x = 70?
5. **Passing lane:** a straight line from carrier to teammate? Is the 2 m
   measured to the line segment? Do teammates in offside positions count?
6. **Facing own goal:** how many degrees either side of the direction to
   (0, 34) still counts? (e.g. ±45°, ±60°)
