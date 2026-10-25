# Football behaviour reference for the Second Ball engine

**Purpose.** This is the football the engine should produce. It turns coaching principles and published tracking-data numbers into rules the simulation can follow. The engine decides everything; the 2D and 3D views only play it back.

**How to read it.**
- Every rule says *what real teams do* and then **Engine:** *what the simulation should do*.
- Every number is a **starting target, TUNABLE**, with its source in brackets, e.g. [12]. Where sources disagree, a range is given.
- Team style (Riverside's 3-2-5, Harbour's 5-4-1 block, press heights, game-state rules) sits on top of these defaults through the club YAML files. Nothing here overrides a club's style; it describes the football every team shares.
- Owner of all thresholds: Ian.

---

## 1. The structure of a match

Coaches split open play into **four moments**: in possession, out of possession, and the two transitions between them (winning the ball, losing the ball) [1][2][3]. Several national associations add **set pieces** as a fifth phase [3].

- **Transitions are short and decisive.** The FA's coaching material treats roughly the first 0–6 seconds after a regain or loss as the critical window [4]; other analysts put it at about 5–8 seconds [5].
- **Each team's shape differs between possession and non-possession**, which is exactly why the moment just after a turnover is dangerous: neither shape is in place yet [2].

**Engine:** every player is always in one of these team states, and the state drives his target position and decisions:

| Team state | Starts | Ends |
|---|---|---|
| `in_possession` (build-up / progression / final third) | ~6 s after a regain, or at a restart | ball lost |
| `attacking_transition` | the instant the ball is won | ~6 s, or the attack settles into possession |
| `defensive_transition` | the instant the ball is lost | ~5–6 s counter-press window ends, or ball regained |
| `out_of_possession` (high / mid / low block) | after the defensive transition | ball won |
| `set_piece` | ball out of play / foul | restart taken |

---

## 2. Principles of play (what every player is trying to do)

The FA lists five attacking and five defending principles [6][7]:

| Attacking (in possession) | Defending (out of possession) |
|---|---|
| **Penetration**: play through, around or over the opponent | **Delay**: slow the attack, deny the preferred next action |
| **Support**: options at good angles and distances for the carrier | **Compactness**: small distances between players and lines |
| **Width** (creating space): stretch the opponent across the pitch | **Cover and balance**: second defender covers the first; far side stays balanced |
| **Movement/mobility**: rotate and run to drag defenders and open space | **Depth**: layered defenders so one beaten player isn't fatal |
| **Creativity**: the unexpected solution (dribble, disguise) | **Control/restraint**: don't dive in; choose the moment |

**Engine:** these become the scoring terms players use when choosing where to stand and what to do (sections 4–8). A good move is one that increases penetration, keeps support and width, and doesn't break the team's rest defence.

---

## 3. Space: lanes, lines and half-spaces

- Teams think of the pitch as **five vertical lanes**: two wide lanes, two **half-spaces**, and the centre [8]. The half-spaces are the inside channels between the wide lane and the centre; from there the ball can go in any direction, and reaching the centre is easier [8].
- A positional-play training rule (Guardiola): **no more than two players in the same vertical lane, and no more than three in the same horizontal line** [9]. Another coaching variant: the top players should each be in a different lane, and the winger and full-back should not share one [10].

**Engine:**
- Split the pitch into 5 lanes. In possession, a spacing penalty when 3+ teammates share a lane or 4+ share a horizontal band.
- Front line in possession aims to occupy all five lanes (for Riverside's 3-2-5 this falls out of the YAML shape naturally).
- Out of possession, the back line protects the three central lanes first and only presses wide when covered [10].

---

## 4. In possession

### 4.1 Build-up (own third)

- Most teams build from the back because it draws the opponent's press forward and opens space behind it [11].
- **Use the goalkeeper as a free player** to recycle and switch [12][13]. A keeper can also hold the ball briefly to invite pressure, then play past it [14].
- **Avoid passing to a full-back in his own half when the opponent is set up to trap there**: it's a common pressing trap (see 5.3) [12].
- **Recycle rather than hope**: if the forward pass isn't on, go back or sideways and switch [12].
- **Switch play** to the far side when the press loads one side [12][15].
- **Know when to go long**: if the press is winning, a long ball is the safer option even for a possession team [16].

**Engine (build-up decision weights, per carrier):**
1. Forward pass to an unmarked player between the lines → highest value when the lane is clear.
2. Pass to a free teammate on the weak side (switch) when the near side is crowded.
3. Back pass to the centre-back or keeper when under pressure with no forward option. **This is normal football, not a failure.**
4. Long ball to the striker or into the channel when pressure is high and options ≤ 1, or when team style says direct (Harbour).
- After a back pass, the team **resets** its shape (full-backs re-widen, midfielders re-offer) before trying again.

### 4.2 Progression (middle third)

- Play into the half-spaces and between the lines; a receiver who drops between the opponent's lines draws defenders and opens space behind [8][17].
- **Third-man runs**: two players exchange passes while a third runs into the space the exchange created [17][18].
- Typical sequence numbers (Premier League): open-play sequences last about **10 seconds** and progress about **12–13 m** upfield on average [19]; passes per sequence range from about **2.8 (direct team) to 5.1 (possession team)** [19][20].

**Engine:** most possessions are short. The engine should produce many 2–5-pass sequences, regular back passes and switches, and occasional long patient spells for possession teams. Sequence length and progress are realism targets (section 12).

### 4.3 Final third and creating chances

- **Overloads**: create 2v1 and 3v2 situations by getting an extra player to the ball side [21].
- **Overlap** (run outside the carrier) and **underlap** (run inside the carrier) [22][23]. The overlap is usually the full-back's job, outside the winger who has the ball [24].
- **Decoy runs** pull a defender out of a space for someone else [25].
- **Crosses and box occupation**: attack set zones, not the same spot: **near post, far post, penalty spot (cut-back), and the edge of the box for second balls** [26][27][28]. For quick counters and low cut-backs, **2–3** well-timed runners are enough; for aerial deliveries and set pieces, **4–6** [29]. When the ball is wide, the **opposite winger attacks the far post** [30].
- **Balance behind the attack**: many teams keep a 2+3 or 3+2 structure behind the ball so a loss doesn't become a counter [29] (see rest defence, 4.4).

**Engine:**
- When the ball reaches a wide area in the final third: assign box runners by role: striker → near post or penalty spot; far winger → far post; an arriving midfielder → cut-back zone or edge of box. Runs start late and arrive with the cross, not before.
- Crosser decision: near post / far post / cut-back depending on where runners are free.
- Count and log overloads near the ball (this already feeds the `overload` metric).

### 4.4 Rest defence (while attacking)

- The players behind the ball while attacking form the **rest defence**: typically **five attack and five stay** in a balanced attack, shifting to **six and four** when chasing a goal [31]. The rest-defence unit usually aims to outnumber the opponent's remaining attackers by one [31].
- How you attack decides how exposed you are to counters [32].

**Engine:** each team keeps a rest-defence count from its style (Riverside's 3-2 base = 5). When chasing (game-state rule), drop to 4. Harbour's counter-attack threat is precisely the gap behind Riverside's advanced full-back when this structure is thin on one side.

---

## 5. Out of possession

### 5.1 Block height

| Block | Typical behaviour |
|---|---|
| **High** | Press near the opponent's box; defensive line high. High-press teams position the line roughly **40–50 yards from their own goal** [33]. |
| **Mid** | Engage around halfway; protect the middle; force play wide. |
| **Low** | Defend close to own box; compact, few spaces between lines. |

- Measured from defensive actions, Premier League line heights range from roughly **38 m (deepest) to about 51 m (highest)** from a team's own goal [34].

### 5.2 Compactness (the numbers)

- In Bundesliga tracking data, defending teams kept the **defence–midfield distance around 10 m** on average, with a team surface area around **790 m²** [35].
- The same study found **compactness near the ball** (the five defenders closest to it) mattered for winning the ball back, more than whole-team compactness [35][36].
- Example team lengths (back line to front line): Al Ahly **26 m in a mid-block, 24 m in a low block**, versus about **32–33 m** for their opponents [37]. Inter in a mid-block: **about 21 m deep and 37.5 m wide**; in a low block, under **17 m** deep [38].

**Engine:**
- Out of possession, team length target by block: high ≈ 30–35 m, mid ≈ 25–30 m, low ≈ 17–25 m (tunable per club).
- Def–mid line gap target ≈ 10 m when organised; the `line_gap` metric shows when it opens (fatigue, red card, chasing).
- The whole block **shifts towards the ball side** as a unit; the far side stays balanced, no further across than a "help line" near the centre of the pitch [39].

### 5.3 Pressing and its triggers

Teams don't press all the time; they press **together** when a trigger happens [40][41]. Common triggers:
- a **back pass** (including to the keeper) [40][42]
- a **poor or heavy touch** [40][42]
- a receiver **facing his own goal** or with his back to goal [40][42]
- the ball near the **touchline** (the line acts as an extra defender) [42][43]
- a **slow, underhit or bouncing pass** [40][42]
- a **square/sideways pass** under pressure, or a receiver with **few options** [43]
- a pass to the **full-back deep in his half**: the classic wide trap [41]

How the press works:
- **First defender presses the ball**; teammates **cut passing lanes** rather than chasing the same player [44]. Pressing runs are **curved**, using the presser's body to block the pass behind him (the "cover shadow") [45].
- Press **in pairs or units**; show the carrier one way (often to the touchline) [44][45].

**Engine:**
- Each frame, compute a `press_trigger` score for the carrier from the list above (facing direction comes from `facing_deg`; touch quality from the event).
- If trigger ≥ threshold and the team's press style allows it at this height: nearest player presses on a curved line that blocks the carrier's best forward pass; the next 1–2 players step onto passing lanes; the back line steps up (5.4).
- If no trigger: hold shape, delay, show outside.

### 5.4 Back-line movement: step up, hold, drop

Coaching rules for the back four [46][47][48]:
- **Ball carrier unpressured, head up, able to play forward → DROP** (protect the space behind).
- **Good pressure on the ball → HOLD or STEP UP.**
- **Opponent plays backwards (negative pass) → STEP UP** together, squeezing space.
- **Pressured carrier plays sideways → HOLD.**
- **Free dribbler running at the line → HOLD, then drop gradually**, keeping distances.
- After a clearance out of the box, the line steps out in stages as the ball goes further away [49].
- The line **moves as one**; a flat line matters because offside is judged against the second-last defender [50].

**Engine:** back-line target depth = function(ball position, pressure on ball, ball direction), applied to all four/five defenders together, with a max step speed so it's never a jump. The goalkeeper's depth follows the line (section 7).

### 5.5 Defending one-on-one and tracking runners

- The first defender **delays**: closes at an angle, slows down near the carrier, stays on his feet, and only tackles when close enough and supported [7][51].
- Defenders track dangerous runs, especially behind the line and blind-side runs [22].

**Engine:** tackle attempts only within reach (≈ 1–2 m, tunable) and preferably when cover exists; otherwise jockey (move backwards with the carrier, between him and goal).

---

## 6. Transitions

### 6.1 Attacking transition (just won the ball)

- **Look forward first**: many of the best goals come before the opponent can reorganise [2].
- But some teams prefer to **secure the ball first**: play the first pass into an area without pressure, then build [5].

**Engine:** on a regain, evaluate the counter: if the opponent's shape is broken (few defenders between ball and goal, rest defence outnumbered) → counter: fast, direct, runners sprint forward. Otherwise → first pass out of pressure, then build. Team style weights the choice (Harbour: counter; Riverside: secure unless clearly on).

### 6.2 Defensive transition (just lost the ball)

- **Counter-press**: press immediately to win the ball back while the opponent is disorganised. The "five-second rule" is a guideline, not a stopwatch [52].
- If the counter-press fails or isn't the team's style, **recover** goal-side and reorganise into the block; many teams prefer this safer option [53].
- Research on defensive transitions finds that regaining the ball quickly after a loss is the most important success factor [54].

**Engine:** on a loss, players near the ball press (count from club `counterpress` setting) for up to ~5 s; everyone else sprints back goal-side towards their block positions. After the window, switch to `out_of_possession`. The engine must show this **recovery run**: it's one of the clearest signs of real football on screen.

---

## 7. The goalkeeper

- **Position on the line between the ball and the centre of the goal**, ideally on the bisector of the shooting angle [55][56].
- **Depth depends on the ball**: further from goal when the ball is far away, closer as it comes nearer [57]. With play in the middle third, keepers commonly stand around the penalty spot or just above it, ready to sweep balls in behind [58].
- **Sweeper-keeper**: with a high line, the keeper covers the space behind it and comes out for through balls [59].
- **Set position** when a shot is coming: square to the ball, balanced, still [57].
- **Distribution**: short to keep the ball and beat a press, or long to bypass it [59][60].
- **Law 12 (2025/26)**: a keeper holding the ball in his hands for **more than 8 seconds** concedes a **corner kick** [61][62]. The count starts when he has control and is not under pressure [62].

**Engine:**
- Keeper always **faces the ball**; position = point on the ball–goal-centre line at depth f(ball distance), clamped inside his area unless sweeping.
- On a through ball he can reach first (time-to-intercept, section 11): come out and sweep.
- On a shot: move to set position, then dive/step towards the ball's path. Dive direction must match the shot.
- In possession: hold ≤ 8 s (usually much less), while teammates spread to offer options; then distribute per team style and pressure.

---

## 8. Off-ball movement catalogue

Each of these is a named behaviour the engine can assign to a player when it fits the situation:

| Movement | What it is | When the engine uses it |
|---|---|---|
| **Show / check to the ball** | move towards the carrier to offer a short option | carrier under pressure, nearest teammates |
| **Run in behind** | sprint into space behind the defensive line | high line, carrier facing forward with time |
| **Overlap** | run outside the carrier [22][24] | full-back behind his winger on the ball side |
| **Underlap** | run inside the carrier [22] | midfielder/full-back when the wide lane is occupied |
| **Third-man run** | third player runs while two others combine [17][18] | a one-two is on and a lane behind opens |
| **Decoy run** | run to drag a defender away [25] | to open a lane for the carrier or another runner |
| **Blind-side run** | run on the side the defender can't see [22] | striker/far winger against a ball-watching defender |
| **Pin the far post** | far winger attacks the far post on a wide attack [30] | ball in a wide area in the final third |
| **Support angle** | offer a diagonal, not a flat, option; form triangles | always, for the 2 nearest teammates |
| **Recovery run** | sprint goal-side after losing the ball | defensive transition |
| **Tracking run** | follow a dangerous runner | defenders/midfielders near the runner's path |
| **Second-ball position** | stand where a header will drop [63][64] | long ball or aerial duel in progress |

Rule for all of them: **a run has a reason and a target**. No player runs away from the play without one of these purposes.

---

## 9. The carrier's decision (one policy)

Inputs per carrier: pressure, options, risk (from `pressure_risk_options.md`), facing, team state, zone, team style, game state, press trigger seen by opponents.

| Situation | Typical decisions (weighted, not fixed) |
|---|---|
| Under pressure, facing own goal, ≤ 1 option | back pass to keeper/CB, lay-off to a supporting player, or shield and turn away from pressure; clear if in own box |
| Under pressure, options available | quick pass to the free support player (often backwards or sideways); one-two |
| Time and space, facing forward | forward pass into a runner or between the lines; carry forward into space |
| Lines broken, defenders running back | carry at speed, then pass/shoot; counter if on |
| Near side overloaded by opponents | switch to the weak side (directly or via CB/keeper) |
| Own overload near ball (e.g. 3v2) | combine (overlap, underlap, third man) to exploit it |
| Wide in final third | cross to a free zone, cut back, or combine inside |
| In shooting range with a clear angle | shoot (xG decides quality, the engine's existing model) |
| Attack stalls in final third under pressure | recycle backwards and **restart the build-up from the back** |
| Team protecting a narrow lead late (game-state rule) | safer passes, slower tempo, more long balls on regain |

**Hard rules:**
- **Every pass has a target**: a teammate, or space a teammate is already running into.
- **Holding time**: outfield carriers act within a few seconds (dribbling counts as acting); the keeper within 8 s with hands.
- **Possession transfers only when the ball arrives** and a player can reach it (time-to-intercept, section 11).

---

## 10. Restarts and stoppages

Ball out of play is a big part of a real match:
- **Ball-in-play time** in the Premier League is about **55 minutes** of a 90+ minute match (54:46 in 2022/23, about 56% of match time) [65][66]. Other big leagues are similar, around 53–57 minutes [67].
- **Typical counts per match**: about **40 throw-ins** (43 in a Premier League study, 40 in La Liga) [68]; about **10 corners** [68][69]; around **30–38 free kicks** [68][70]; around **20–30 goal kicks** [69][70].
- **Typical delays**: a throw-in takes about **16 seconds** to restart; free kicks, corners and goal kicks about **30 seconds** each on average [65].

**Engine:**
- Ball out → ball state `out_of_play` at the exact spot → restart type decided (throw-in / goal kick / corner) → the nearest suitable player **walks or jogs** to the spot → teammates move into restart positions → restart taken (a throw-in can be animated as a short pass from the touchline) → play resumes.
- Goal → scorer and teammates converge (celebration) → everyone walks back to their own half → kick-off positions → kick-off. **No time skips and no jumps.**
- Fouls → free kick at the spot; for a red card the sent-off player **walks off**.
- Half-time: players walk off/on; second half starts from kick-off positions with ends swapped.
- Realism targets: restart counts and ball-in-play time above (section 12).

---

## 11. Movement physics and reachability

### 11.1 Speeds and distances (published tracking data)

- **Distance covered**: international players cover roughly **8–14 km** per match, about 80–90% of it at low intensity [71]. In the Premier League, high-running midfielders reach **11–12 km per 90**; centre-backs are among the lowest outfield (**about 8.7–8.9 km**); goalkeepers about **4 km** [72].
- **Speed bands** (common definitions): high-speed running **19.8–25.2 km/h (5.5–7 m/s)**; sprinting **≥ 25 km/h (≈ 7 m/s)** [72][73].
- **Top speeds**: the slowest Premier League outfield regulars still reach about **29.5 km/h**; the fastest players **around 35 km/h (≈ 9.7 m/s)**; a goalkeeper's top speed about **32 km/h** [72][74].
- **Sprint counts**: the most intense attackers make **50–60 sprints per match** (≥ 25.2 km/h) [74]; most players far fewer.

**Engine:**
- Movement states with speed caps: walk (≤ 2 m/s), jog (≤ 4), run (≤ 5.5), high-speed (≤ 7), sprint (≤ 9.5, player-specific, 8–9.7).
- Acceleration limit (≈ 3–4 m/s², tunable) and turning limit at speed; no instant direction changes.
- Players are mostly walking/jogging; sprints are for transitions, runs in behind, recovery runs and pressing.
- **Teleport rule**: any step implying > 10 m/s for a player is a bug (the ball and its own limits are separate).

### 11.2 Time-to-intercept (who gets there first)

- The pitch-control model used at Liverpool (Spearman) estimates **how long each player needs to reach a point**, using his position, current velocity, reaction time and maximum speed, with a logistic curve for uncertainty [75][76]. A widely shared simple implementation uses about **0.7 s reaction time** and a **5 m/s** maximum speed, with arrival-time uncertainty around **0.45 s** [77].
- The same time-to-intercept idea has been extended to measure **pressing intensity** frame by frame [78].

**Engine uses for time-to-intercept:**
- **Interceptions**: an interceptor can only win a pass if he reaches a point on the ball's path before it passes. He **runs there**; never placed there.
- **Receiver choice**: prefer passes the receiver reaches well before any defender.
- **Pressing**: the presser is the player who reaches the carrier fastest, not simply the nearest.
- **Keeper sweeping**: he comes out only if he wins the race to the ball.
- Use realistic player speeds (11.1), not the simplified 5 m/s, for movement; the simple model is fine for the probability part.

---

## 12. Aerial duels and second balls

- After a long ball, the first contact is often a 50/50 header; **possession is decided by the second ball** [63].
- Teams position support players **behind and around** the player contesting the header to win the drop [64]. One study treats the ball as recovered if a recovery or pass follows within **2–3 seconds** of the duel [63].
- Weaker teams contest more aerial duels and recover more second balls than stronger teams [79].

**Engine:** on a long ball: target and marker contest at the landing point; the header goes in a random but plausible direction (flick-on or knock-down); 1–2 players per team move to the expected drop zone; whoever reaches the drop first (time-to-intercept) wins it.

---

## 13. The referee

- Referees use the **diagonal system of control**, patrolling roughly from corner to corner while keeping play between themselves and an assistant referee [80][81]. They leave the diagonal to get closer to play when needed [82], staying towards the outside of play to keep the lead assistant in view [83].
- In one study of referees' positions, most of the time they were **5–30 m** from the ball [84].

**Engine:** referee target = a point on his diagonal, shifted towards play, 10–25 m from the ball and out of passing lanes; same speed and teleport limits as players; jogs to restarts.

---

## 14. Realism targets (add to DATA_REALISM.md with these sources)

| Measure | Target | Source |
|---|---|---|
| Ball-in-play time | ~53–57 min per match | [65][66][67] |
| Passes per match (both teams) | ~850–945 (Premier League, recent seasons) | [19][20] |
| Long balls per match | ~95–100 | [20] |
| Open-play sequence duration | ~10 s average | [19][20] |
| Passes per sequence | ~2.8 (direct) to ~5.1 (possession) | [19][20] |
| Throw-ins per match | ~40 | [68] |
| Corners per match | ~10 | [68][69] |
| Free kicks per match | ~30–38 | [68][70] |
| Goal kicks per match | ~20–30 | [69][70] |
| Distance per outfield player | ~9–12 km (CB lowest, ~8.7–8.9) | [71][72] |
| Goalkeeper distance | ~4 km | [72] |
| Top speed (outfield) | ~29.5–35 km/h | [72][74] |
| Def–mid distance (organised) | ~10 m | [35] |
| Team length out of possession | ~17–33 m depending on block | [37][38] |
| Defensive line height | ~38–51 m from own goal | [34] |

Don't tune the engine to hit every number in one match; check them across many matches, as with the existing realism report.

---

## 15. Acceptance checks for the engine work

Watch with the sound off and check, in 2D and 3D:

1. **Nobody teleports**: players, ball, referee (speed caps above).
2. **Every pass has a target**, and the receiver moves to meet the ball.
3. **The passer keeps moving** after passing (support, overlap, or rest-defence position).
4. **Team moves as a unit**: the block shifts with the ball; the line steps up and drops together.
5. **Pressing happens on triggers**, with cover behind the presser, not 3 players chasing one.
6. **Recovery runs** after every loss; counter-press for a few seconds where the style says so.
7. **Keeper faces the ball**, follows the ball–goal line, sets for shots, dives the right way, releases within 8 s.
8. **Restarts are walked to**, never jumped; goals have a celebration and walk-back; the sent-off player walks off.
9. **Back passes and restarts from the back happen** when attacks stall under pressure.
10. **Box occupation on crosses**: near post, far post, cut-back, edge of box.
11. **Realism table (section 14)** within range across 20+ free matches.

---

## Sources

[1] Just Coach newsletter, "The 4 moments": https://justcoachmd.substack.com/p/21-grow-coach-newsletter
[2] Cupello, "Four tactical intentions": https://www.cupello.com/blog/coaching-youth-soccer-using-four-tactical-intentions
[3] Voor.sport, "Phases of play in football" (Van Gaal; ÖFB/DFB set pieces): https://voor.sport/es/mag/phases-of-play-in-football
[4] The FA (Hunts FA), transition event notes: https://thefa.com/-/media/cfa/huntsfa/files/coaching/documents/transition-event.ashx
[5] Jobs in Football, "What is a transition in soccer": https://jobsinfootball.com/blog/what-is-a-transition-in-soccer/
[6] England Football Learning, "What are the principles of football": https://learn.englandfootball.com/articles/resources/2022/What-are-the-principles-of-football
[7] Football DNA, defensive principles: https://footballdna.co.uk/?p=41007
[8] Coaches' Voice, "The half-spaces": https://learning.coachesvoice.com/?p=57163
[9] Sport Session Planner, "Half Spaces" (Guardiola zone rules): https://www.sportsessionplanner.com/s/I9gJh/Half-Spaces.html
[10] Sport Session Planner, "Introduction to the lanes": https://sportsessionplanner.com/s/Er9Rh/Introduction-to-the-lanes.html
[11] FIFA Training Centre, Mexico U15 "Possession and building from the back": https://www.fifatrainingcentre.com/en/practice/elite-sessions/youth-national-teams/mexico-u15-boys-/possession-and-building-from-the-back-flores.php
[12] FIFA Training Centre, session plan (Lehmann): https://www.fifatrainingcentre.com/media/native/test/FIFA_Session_Plan_Lehmann2.pdf
[13] FIFA Training Centre, "Role of the goalkeeper" (Olympic tournament): https://fifatrainingcentre.com/en/game/tournaments/olympic-football-tournament/moft/role-of-the-goalkeeper.php
[14] FIFA Training Centre, Club World Cup 2025 roundtable on high presses: https://www.fifatrainingcentre.com/en/game/tournaments/fcwc/2025/team-analyses/tsg-roundtable-analysing-solutions-against-teams-that-press-high.php
[15] Sport Session Planner, switches to bypass a press: https://www.sportsessionplanner.com/s/XCXGi
[16] Guide to Football, "Playing out from the back": https://guidetofootball.com/tactics/playing-out-from-the-back/
[17] Coaches' Voice, "Third-man runs": https://learning.coachesvoice.com/?p=53456
[18] Football Paradise glossary, underlap / third-man run: https://www.footballparadise.com/en/glossary/underlap
[19] Premier League / Opta Analyst, long balls and sequences 2025/26: https://www.premierleague.com/en/news/4426039/opta-analyst-on-long-balls-long-throws-key-tactical-trends-spotted-in-2025-26-season
[20] Opta Analyst, passes per game 2025/26: https://theanalyst.com/?p=229083
[21] Sport Session Planner, creating and using overloads: https://www.sportsessionplanner.com/s/QVXzi/U11s-PoP-Creating-and-Using-Overloads.html
[22] Sport Session Planner (FAI), overlap, underlap, blind-side and third-man runs: https://www.sportsessionplanner.com/s/iAnci/Overlap-Underlap-Blindside-Run-and-Thirdman-Run..html
[23] Driblab, off-ball runs: https://www.driblab.com/blog/arrigo-off-ball-runs
[24] We Make Footballers, "Understanding overlapping": https://wemakefootballers.com/news/understanding-overlapping-in-football
[25] FIFA Training Centre, pass and overlap / decoy run: https://www.fifatrainingcentre.com/media/native/test/37-pass-and-overlap-new.pdf
[26] Sport Session Planner, "Types of cross": https://www.sportsessionplanner.com/s/8iIR/Types-of-Cross.html
[27] Sport Session Planner, cross with numbers in the box: https://www.sportsessionplanner.com/s/47TQh/18-Attacking---cross-into-space-with-numbers-in-the-box-in-the-offensive-third---Load-75-.html
[28] Elite Soccer Coaching, crossing and finishing: https://elitesoccercoaching.net/in-possession/crossing-and-finishing6
[29] Fussball Coaches Newsletter, "How top teams fill the box": https://fussballs-newsletter-4ebdfb.beehiiv.com/p/how-top-teams-fill-the-box-b477
[30] Elite Soccer Coaching, attacking centrally (pin the far post): https://elitesoccercoaching.net/in-possession/creating--finishing/attacking-centrally
[31] Coaches' Voice, "What is rest defence?": https://learning.coachesvoice.com/?p=71763
[32] Squawka, "What is rest defence?": https://www.squawka.com/en/?p=1422777
[33] Football Paradise glossary, pressing trigger: https://www.footballparadise.com/en/glossary/pressing-trigger
[34] StatsUltra, "The role of defensive line height": https://statsultra.com/?p=1675
[35] Forcher et al., compact organisation and defensive success (tracking data): https://https-sage-cnpereading-com-443.webvpn1.xju.edu.cn/doi/10.1177/17479541231172695
[36] Forcher et al., record (Univ. Vienna): https://ucrisportal.univie.ac.at/en/publications/is-a-compact-organization-important-for-defensive-success-in-elit/
[37] FIFA Training Centre, Al Ahly block defending: https://fifatrainingcentre.com/en/game/tournaments/fcwc/2023/using-block-defending-and-central-pressure-to-negate-world-class-players.php
[38] UEFA, Inter's defensive organisation: https://de.uefa.com/uefachampionsleague/news/0294-1c8f90c6286b-8783898ac1e1-1000--champions-league-performance-insights-inter-s-defensive-r
[39] Football DNA, balance and the "help line": https://footballdna.co.uk/?p=41007
[40] England Football Learning, press and cover session: https://learn.englandfootball.com/sessions/resources/2025/Session-programme-press-and-cover-to-defend
[41] Sport Session Planner, mid-block pressing traps: https://www.sportsessionplanner.com/s/wURWi/Mid-Block-pressing-triggers.html
[42] Sport Session Planner, pressing from the front (triggers): https://www.sportsessionplanner.com/s/nT2Jh/PRESSING-FROM-THE-FRONT.html
[43] Sport Session Planner, winning the ball back early (triggers): https://www.sportsessionplanner.com/s/AZ0Dh/Win-the-ball-back-early-to-create-goal-scoring-opportunities.html
[44] FootballGPT, pressing trap drill: https://www.footballgpt.co/drills/pressing-trap-drill
[45] FootballGPT, pressing as a player (curved runs): https://footballgpt.co/player/pressing-as-a-player
[46] Sport Session Planner, defending with a back 4: https://sportsessionplanner.com/s/Runkb
[47] Sport Session Planner, step up / step down: https://www.sportsessionplanner.com/s/9YQ1i/Defender-Session-Step-Up-Step-Down.html
[48] Sport Session Planner, when to drop and push up (U15): https://www.sportsessionplanner.com/s/wyRqb/Recognising-when-to-drop-and-when-to-push-up-Back-four---U15s.html
[49] Sport Session Planner, 3-phase push-up: https://sportsessionplanner.com/s/EQF8h
[50] Guide to Football, "The offside trap": https://guidetofootball.com/tactics/offside-trap/
[51] Prezi, roles in a 4-3-3 (delay, jockeying): https://prezi.com/iyh3n-gb8mzl/roles-responsibilities-in-a-4-3-3-system-of-play/
[52] Guide to Football, "Counter-pressing": https://guidetofootball.com/tactics/counter-pressing/
[53] iDiski Times, transitions explained: https://www.idiskitimes.co.za/?p=266304
[54] Journal of Sports Science and Medicine, defensive transition study: https://jssm.org/jssm-22-707.xml
[55] Angle bisector geometry (goalkeeper positioning): https://ejournals.eu/pliki_artykulu_czasopisma/pelny_tekst/ac1024df-c6ab-44fb-af2b-61f58325dbb5/pobierz
[56] Goalkeeper angle-shutting article: https://footballkit.lazada.com.ph/players/guillermo-ochoa-technical-analysis-decoding-the-spatial-telepathy-behind-his-angle-shutting-geometry/
[57] KeeperStop, angles and positioning: https://www.keeperstop.com/blogs/goalkeeper_drills-angles_positioning
[58] KeeperStop, how far off the line: https://www.keeperstop.com/goalkeeper_drills-angles_positioning-how_far_off_the_line_should_the_goalkeeper_be
[59] Goalkeeper contributions (sweeping, distribution): https://gravitee.io/corpus/gen-2265/2018-19-c-d-guadalajara-women-season/goalkeeper-contributions.html
[60] FIFA Training Centre, goalkeepers' build-up session: https://fifatrainingcentre.com/en/practice/elite-sessions/goalkeeper/goalkeepersbuildup.php
[61] The IFAB, goalkeeper time-wasting law change: https://www.theifab.com/news/the-ifab-tackles-goalkeeper-time-wasting
[62] The IFAB, Law 12 2025/26 background and Q&A: https://downloads.theifab.com/downloads/law-changes-2025-26-goalkeepers-controlling-the-ball-with-their-hand-s-arm-s-back
[63] Marc Lamberts, expected second ball retention: https://marclamberts.substack.com/p/introducing-expected-second-ball
[64] Spielverlagerung, "The art of the long ball": https://spielverlagerung.com/2020/08/13/the-art-of-the-long-ball/
[65] Opta Analyst, guide to Premier League time-wasting: https://theanalyst.com/?p=71182
[66] Opta Analyst, ball-in-play 2022/23: https://theanalyst.com/na/2023/05/guide-to-premier-league-time-wasting/
[67] StatsBomb, ball-in-play across the big five leagues: https://statsbomb.com/?p=53082
[68] Stone et al., throw-in strategy (incl. corners and free kicks per match): https://shura.shu.ac.uk/35132/1/Stone-AnalysisOfThrowInsStrategy%28AM%29.pdf
[69] MBP School, set-piece actions: https://mbpschool.com/en/?p=530001
[70] Analysis of match actions, 1994 World Cup: https://ir-library.ku.ac.ke/items/920e4724-d747-420c-bfac-ecd05e0c55e1
[71] South African PSL physical demands study: https://journals.assaf.org.za/index.php/sajsm/article/view/16752
[72] Opta Analyst, Premier League running data 2025/26: https://theanalyst.com/?p=240213
[73] Driblab, high-speed runs: https://www.driblab.com/blog/player-analysis-what-can-high-speed-runs-tell-us
[74] Training Ground Guru, UEFA speed and sprint data: https://trainingground.guru/articles/premier-league-pushes-european-speed-limits-again
[75] Training Ground Guru, William Spearman on pitch control: https://archive.trainingground.guru/articles/william-spearman-how-liverpool-create-pitch-control
[76] Summary of Spearman et al., physics-based pass probabilities: https://thexgfootballclub.substack.com/p/the-perfect-pass-formula-can-physics
[77] Tony ElHabr, pitch control implementation notes: https://tonyelhabr.rbind.io/post/soccer-pitch-control-r/
[78] Bekkers, "Pressing Intensity" (arXiv): https://arxiv.org/abs/2501.04712v2
[79] DBpia, aerial duels and second balls by team strength: https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE11958321
[80] AYSO, the diagonal system of control: https://wiki.ayso.org/w/images/Diagonal_System_of_Control.pdf
[81] Reading Referees, nearness to play: https://www.readingrefs.org.uk/ftm/ftmpages/FTM180.html
[82] Reading Referees, the diagonal system: https://readingrefs.org.uk/ftm/ftmpages/FTM380.html
[83] The IFAB, positioning, movement and teamwork: https://theifab.com/laws/latest/guidelines/positioning-movement-and-teamwork
[84] Univ. Évora, referee distance to the ball: https://rdpc.uevora.pt/handle/10174/29908
