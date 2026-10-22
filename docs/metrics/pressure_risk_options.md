# Pressure, risk, options and "bad_situation"

Status: **spec only**. No metric code until Phase 2.
Red zone: thresholds are Ian's decisions. Agents never change them.

Every number marked **TUNABLE** is owned by **Ian**. Change it here first,
then in code, then re-run evals. Lines marked **(Ian, 2026-10-20)** are Ian's
answers to the first round of questions.

## Conventions

Taken from the contracts (`core/contracts/event.py`):

- Pitch 105 × 68 m. SPADL convention: the acting team attacks towards x = 105,
  so its **own goal is at (0, 34)**.
- `facing_deg`: 0° points along +x, 90° along +y, anticlockwise, range [0, 360).
- All inputs come from one `MatchEvent`: the ball carrier is `player_id` at
  (`start_x`, `start_y`); other players come from `freeze_frame`.

## pressure (0–1)

How hard the ball carrier is being pressed. Proximity only.

- Count opponents within **5 m** of the ball carrier. **TUNABLE** (owner: Ian)
- Each opponent adds weight by closeness: closer means more weight.
- **Close = within 2 m.** How fast a gap closes depends on the player (a quick
  or sliding defender closes 2.5 m fast), but 2 m is the line.
  **TUNABLE** (Ian, 2026-10-20)
- **One opponent within 2 m is enough for `under_pressure`**: a single close
  opponent must give pressure ≥ 0.5. (Ian, 2026-10-20)
- An opponent **in front** of the carrier or **goal-side** of the carrier
  (between the carrier and the goal he is attacking) counts **double**
  (weight × 2); both at once is still × 2 (Ian, 2026-10-22). **TUNABLE** (owner: Ian)
  - **"In front" = in front of where the carrier is facing.** A defender
    facing their own keeper with a striker pressing from upfield: the striker
    is *behind*. A defender facing upfield with the same striker pressing: the
    striker is *in front*. (Ian, 2026-10-20)
- Result is in 0–1.
- `under_pressure = pressure >= 0.5`. **TUNABLE** (owner: Ian)

## risk (0–1)

How costly losing the ball here would be.

- Based on the ball's distance to the carrier's own goal.
- High inside the own penalty box (x ≤ 16.5, 13.84 ≤ y ≤ 54.16).
- **Falls smoothly** the further the ball is from the carrier's own goal.
  (Ian, 2026-10-20)
- Low in the final third (x ≥ 70), but **only about 0 when the attack clearly
  has the upper hand**: no defenders left, or a counter-attack where attackers
  outnumber defenders with clear passing lanes and triangles.
  (Ian, 2026-10-20)
- **"Upper hand" = the attack is on top right now** (Ian, 2026-10-21):
  - many touches in the opponent's final third, around their goalkeeper, **and**
  - shot attempts, on or off target.
  - Final-third play **with no threat** (no shots) is **not** the upper hand.
  - Not measured by possession or pass counts.
  - **xG counts, but only as support** (Ian, 2026-10-21): final-third play +
    shots + xG = a strong upper hand. xG alone is **not** the upper hand: a
    team under pressure can build xG from two counters and one lucky corner.
    xG's weight must stay small. **TUNABLE** (owner: Ian)
  - **Strong upper hand:** the touches + shots rule holds **and** total xG in
    the window ≥ **0.5**. **TUNABLE** (Ian, 2026-10-21)
  - **Window:** a **sliding 10-minute window** is the main one
    (Ian, 2026-10-21). Code also computes the **last 5, 15, 20 and 30
    minutes**; never drop them.
  - **Fixed checkpoints** every 10 minutes (10', 20', 30', ...) as well as the
    sliding window. (Ian, 2026-10-21)
  - **A human chooses what to show.** Code computes every window; the person
    approving the overlay picks one (e.g. the last 5 minutes, if a change in
    those minutes gave this team the upper hand). (Ian, 2026-10-21)
  - **Rule in the window:** at least **10 touches** in the opponent's final
    third **and** at least **2 shots** (on or off target). **TUNABLE**
    (Ian, 2026-10-21)
  - **Where:** the opponent's final third (not only the box), **with constant
    pressure on their defenders.** (Ian, 2026-10-21)
  - **Constant pressure** = in the window, at least **half** of the
    defending team's touches in their own third happen with an attacker
    within **2 m**. **TUNABLE** (Ian, 2026-10-21)
- Ian notes it also depends on the situation, e.g. a team playing a high press.
- **Version 1 includes the situation, not distance only.** (Ian, 2026-10-20)
- Exact curve and values: **TUNABLE** (owner: Ian)

## options (int)

How many safe passes the carrier has.

- Count teammates whose passing lane has **no opponent within 2 m** of it.
  **TUNABLE** (owner: Ian)
- A passing lane is the **straight line** from the carrier to the teammate.
  (Ian, 2026-10-20)
- A teammate who is **clearly offside does not count** as an option.
  (Ian, 2026-10-20)

## Facing own goal

- Facing more than **90°** away from the attacking direction = starting to
  turn back.
- Facing **120°** or more away = clearly facing own goal, i.e. `facing_deg`
  between 120° and 240°. This is the "facing own goal" in `bad_situation`.
  **TUNABLE** (Ian, 2026-10-20)

## Moment: `bad_situation`

Rule:

```
bad_situation = risk >= 0.6
                AND facing own goal
                AND (pressure >= 0.5 OR options == 0)
```

| Condition | Threshold |
|---|---|
| risk | ≥ **0.6** (TUNABLE, owner: Ian) |
| facing own goal | `facing_deg` between **120°** and **240°** (TUNABLE, owner: Ian) |
| pressure | ≥ **0.5** (TUNABLE, owner: Ian), **or** |
| options | == **0** (TUNABLE, owner: Ian) |

Note: options == 0 with no nearby opponent = lane pressure (cover shadows);
pressure measures proximity only.

Evidence: the moment's `evidence_event_ids` must include the event that
triggered it.

## Overloads (backlog, Phase 2)

Attackers vs defenders around the ball, e.g. 3v2 or 3v1. (Ian, 2026-10-20)

- **Not a small fixed circle.** 10 m is too small.
- **Where on the pitch matters.** Final third with no defender left behind is
  dangerous. A 3v2 in a corner is much less dangerous.
- **Count who can still recover.** After a 3v2 is beaten, another defender may
  come across, so defenders left between the ball and goal matter.

## Answers (Ian, 2026-10-22)

All five questions are answered.

1. **Pressure between 2 m and 5 m:** an opponent at 2 m is *really high*
   pressure; at 5 m it is *a bit, low*, not nothing. Proposed curve to build
   with (confirm when pressure is built): weight 1.0 within 2 m, falling in a
   straight line to 0.2 at 5 m, 0 beyond 5 m. **TUNABLE**
2. **Defender both in front of the carrier and goal-side** (between him and
   the goal he is attacking): counts **x2**, not x4. It is one situation,
   the defender blocking his way, so it is doubled once. **TUNABLE**
3. **High press** = how a team behaves the moment it loses the ball:
   - A high-pressing team **tries to win it straight back** instead of falling
     deep; if it has not won it back within **3-5 seconds**, it drops deep.
   - A team that does **not** high-press does not commit players up front: it
     lets the opponent's defenders and goalkeeper play out from the back.
   - Code: (a) after each turnover, count the pressing team's defensive
     actions and opponents within 2 m of the carrier in the first 3-5 s
     (counterpress); (b) when the opponent plays out from the back (goal kick,
     keeper or defender on the ball in their own third), count pressing
     players in that third. High both = high press. **TUNABLE**
4. **Overload area** (agent's proposal, Ian: ok):
   - Look at the ball's surroundings in a box that reaches **20 m towards the
     defending goal and 10 m back**, the full width of the channel the ball
     is in (left, centre or right third of the pitch width).
   - Attackers = the attacking team's outfield players in that box.
     Defenders = the defending team's outfield players in that box **plus any
     defender within 10 m of it who is goal-side of the ball** (they can still
     recover).
   - Danger weight by place: central final third 1.0, wide final third 0.5,
     middle third 0.3, own third 0.1.
   - Overload = attackers minus defenders >= 1 (e.g. 3v2, 3v1).
5. **"Clearly offside" = 1 metre or more** beyond the second-last defender.
   **TUNABLE**
