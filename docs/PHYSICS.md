# Physics-first engine: assumptions and tolerances

The physics-first engine lives in `engine/play/`, behind its own entry point:

```
uv run python -m engine.play --seed 29 --out runs/drill-29
```

The current engine (`engine.core.sim`) is still the default; nothing in
`engine/play/` changes it. This page lists every physical assumption the new
engine makes, where the number comes from, and how far movement may vary
before a test calls it a bug. The numbers live in `engine/config/play.yaml`.

## Stage 1: the drill pitch

One attacker, one defender, one keeper and a loose ball. The attacker drives
at goal and takes a heavy touch. From then on nobody is told who wins the
ball:

- each player reads the ball's predicted path;
- he runs for the first point he can reach no later than the ball;
- whoever gets there and can control the ball has it.

An event is written only then.

## The ball (`engine/play/ball.py`)

| Assumption | Value | Source / reasoning |
|---|---|---|
| Rolling resistance on dry natural grass | 1.2 m/s² | The FIFA Quality Programme ball-roll test: a ball released from a 1 m ramp (about 3.7 m/s) rolls 4–10 m on approved turf, so about 0.7–1.7 m/s². 1.2 is the middle. |
| Air drag | a = k·v², k = 0.0133 per metre | ½·ρ·Cd·A/m, with ρ 1.2 kg/m³, Cd 0.25 (a ball above about 12 m/s), A 0.038 m², m 0.43 kg. |
| Gravity | 9.81 m/s² | |
| Bounce on grass | restitution 0.6; keeps 85% of its ground speed per bounce | The FIFA rebound test on natural grass gives about 0.55–0.65. |
| Integration | 0.02 s sub-steps inside each 0.1 s step | Keeps the bounce and drag stable. |
| A dribbled ball | 0.6 m in front of the carrier | |

## The players (`engine/play/player.py`)

| Assumption | Value | Source / reasoning |
|---|---|---|
| Top speed | 8.5 m/s | Elite sprint peak, about 9–10 m/s, taken a little lower for a typical match sprint. The same figure as the current engine. |
| Speeding up | 3.5 m/s² | Average over a sprint from standing (the first steps are higher). Same as the current engine. |
| Slowing down | 5.0 m/s² | Same as the current engine. |
| Turning (sideways) | 5.0 m/s² | Bending a run or cutting. Kept separate from speeding up, so a runner can curve onto a ball. **To check against data.** |
| Reaction to a new ball | 0.25 s | Simple visual reaction time is about 0.2–0.3 s. |
| Chasing a ball | timed to arrive 0.2 s before it, at no more than top speed | |
| Final approach (within 3 m) | straight at the ball, aimed 0.2 s ahead, at the ball's speed + 2.5 m/s | Both reference engines close the last metres like this (see the audit). |
| Bodies | centres never closer than 0.7 m; eased apart at most 0.05 m a step | |
| Keeper going down on the ball (smother) | stops at 25 m/s², about 1.5 m from a sprint | |

## Winning the ball

- **Reach:**
  - feet: 0.8 m, ball no higher than 0.9 m, moving at most 16 m/s relative to the player;
  - keeper's hands: 1.4 m, up to 2.6 m high.
- **Hands only inside the area:** a keeper may use his hands only if he will also stop inside his area. Otherwise he plays it with his feet like anyone else (`keeper_won_at_feet`).
- **Earliest point, not nearest player:** a player's time to a point is his reaction left, plus the time to kill any speed going the wrong way, plus the run, accelerating to top speed. He chases the first point on the ball's path he can reach no later than the ball. Only the best-placed player of each team chases.
- **Who gets it:** whoever is within reach first, with the ball low and slow enough. If two are within reach on the same step, the nearer one has it.
- **Just kicked:** the player who has just kicked the ball cannot play it again for 0.3 s.

## Events (what is written, and when)

| Moment | Event | Where it sits on the track |
|---|---|---|
| The heavy touch | `bad_touch` (fail) | The sample where the ball is still at his feet |
| An opponent wins the loose ball | `interception` (success) | The sample where he has it |
| The keeper claims it in his hands | `keeper_pick_up` (success) | The sample where he has it |
| The same team gets its own loose ball back | No event (the current engine does the same); the drill result records `won_sample` | |

Events carry whole seconds (the contract). The screen anchors each event at
its exact sample time, so playback runs at the engine's speed.

## Test tolerances (`tests/unit/test_play_drill.py`)

| Check | Tolerance | Why |
|---|---|---|
| A simulated run versus the reach estimate | ±0.4 s | The estimate ignores the arrival slow-down and the 0.1 s steps. |
| A rolling ball | never further than friction alone would allow (+0.2 m); a slow ball (4 m/s) at least 90% of it | Drag only shortens a roll, and barely at low speed. |
| First bounce of a 10 m/s lofted ball | 4.0–5.1 m | 5.1 m is the height without drag. |
| Freeze frame versus track | ≤ 1.1 cm | Events are rounded to the centimetre. |
| Player speed between samples | ≤ top speed + 0.5 m/s | A body push on top of a sprint. |
| Teleports | none; players ≤ 10 m/s, ball ≤ 40 m/s (Ian's definition) | |
| A chaser running alongside a loose ball | at most 1.5 s within 2 m without taking it | Ian's "someone near the ball ignores it". |
| Same seed | byte-identical events and tracks | |

## Known limits of Stage 1

- **Nothing happens after someone wins the ball** beyond holding it, shielding, or a plain drive at goal. There are no tackles, passes or shots (Stages 2 and 3). An attacker who keeps it runs at goal and stops near the goal line.
- **The referee is not in the new engine.** The 3D view still places him by its own rule.
- **The defender only wins balls knocked close to him (within about 0.7 s).** He never wins a long race, because the attacker is already running the ball's way.
- **No animation for a smother, dive or tackle.** The bodies move right; the poses don't show it yet.

## Stage 2: the attack (`engine/play/game.py`)

```
uv run python -m engine.play --attack --seed 76 --out runs/attack-76
```

The set-up:

- Riverside: a midfielder (the feeder) and the striker.
- Harbour: a centre-back, a midfielder (the outlet) and the keeper.

The feeder playing the striker in is the scenario's starting move. After that
nothing is scripted: every player re-decides about every 0.4 s (and at once
when the ball changes hands or is struck), from the live ball, his opponents,
the space and the goal. Values are in `engine/config/play.yaml`
(`game`, `carry`, `defend`, `shoot`, `keeper`, `passing`, `clear`).

| Behaviour | How it works | Assumption |
|---|---|---|
| Dribbling | The ball goes out from the feet and back each touch: up to 0.9 m every 0.45 s with a man within 4 m, up to 2.0 m every 0.9 s in space. Carry speed is 4.5 or 6.5 m/s. | Touch rhythm from typical dribbling footage. |
| Where to carry | 16 headings are scored on progress plus room minus turning. An attacker's progress is towards a point on the goal's centre line 12 m ahead (never nearer goal than 6 m), so he comes inside rather than running down the byline. He keeps his heading unless a new one is better by 0.12 (no zig-zag). | |
| Knocking it past a man | When the man in front is flat-footed (under 1.2 m/s), off balance or lunging, the attacker pushes the ball 5 m at ±40° into space and runs after it. It is a real loose ball. | |
| Jockeying | Sprint in, then 1.8 m goal-side and 0.5 m to the inside (showing him wide), at the carrier's speed + 1.5 m/s. | |
| Tackling | He goes in (a 0.35 s lunge, reaching 1.25 m) after a 0.15 s read when either: the ball is 0.85 m or more off the carrier's foot; or it is as close to him as to the carrier; or the carrier is within 24 m of goal and he has been tight on him for 1 s (he must commit). | |
| What a tackle does | Foot on the ball: won clean 15% + 40% × how loose it was, ±10% from in front or behind; poked loose 30%; otherwise the carrier rides it. A miss leaves the defender off balance for 0.8 s. | About 55–60% of duels go the defender's way (FootySim's calibration table; in our runs, 61%). |
| A moment to settle | Nobody can go in on a man who has just won the ball for 0.8 s. | FootySim's "duel grace". |
| Passing | A pass is played only if, by the ball's real path, the receiver beats every opponent to it by 0.3 s, with opponents reacting 0.25 s after the strike. Aim error is 1.8°, plus 4° under pressure. | |
| Shooting | xG from the current engine's model, × 0.6 for each body within 1.2 m of the line to goal. He shoots at xG ≥ 0.22, or ≥ 0.08 with a man within 2.5 m, or within 11 m with a clear lane. He aims 0.6 m inside the post the keeper covers least. Error is 2° + 0.08° per metre + 3° under pressure; 23–29 m/s; crossing the line at 0.2–1.6 m. | Shot speeds: 85–105 km/h. |
| The keeper | 0.2 s reaction; dives for the first point of the shot's path he can reach (dive 5 m/s, 30 m/s²), hands 1.0 m + 0.3 m at full stretch, up to 2.6 m high. He holds the ball if it is 27 m/s or slower and within 0.7 m of his body; otherwise he parries it (35% of its speed, wide, a real loose ball). Off his line by 11% of the ball's distance; 30% (up to 8 m) when a man is through on him. | |
| A goal | The ball crosses the goal line between the posts and under the bar (checked along its path, not only at the samples). The net is a box 2 m deep that stops it. A ball within a post's radius bounces off the post. | |
| Clearing | A defender with no safe pass and a man on him in his own third clears it 35–50 m up the pitch, high, towards his touchline. | |

**Events.** A pass, shot or clearance is stamped at the strike (its sample and
its second) and written when its result is known: before the save,
interception, tackle or goal that follows it. Anything that happens to a ball
still in the air first settles it; a pass cut out by a tackle is a failed pass.
A carry of 3 m or more is a `dribble` stamped where it began. A carrier going
past a man who was in front of him within 3.5 m is a `take_on`. The time from
the strike to the ball crossing the line is recorded with the shot
(`goal_line_s`).

**Over 100 attacks:**

| Ending | Attacks |
|---|---|
| Harbour clears it long | 29 |
| Harbour passes it out | 25 |
| Keeper holds a shot | 17 |
| Keeper gets it and distributes | 12 |
| Shot misses | 11 |
| Goal | 6 |

| Event (all 100 attacks) | Count |
|---|---|
| Shots | 73 |
| Goals | 6 (8% of shots) |
| Saves (17 held, 30 parried) | 47 |
| Tackles won | 92 |
| Lunges missed or ridden | 63 |
| Dribbles past a man | 130 |
| Clearances | 32 |
