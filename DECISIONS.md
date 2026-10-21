# Decisions

This hackathon displaces Unit 1 weeks 2–3; Unit 1 resumes 28 Oct.



Backlog metrics (define in Phase 2): line gap (mid–def distance),
overload count near ball (e.g. 3v2), red-card before/after comparison.
Engine must be able to produce these situations (Phase 1 knobs).

Exception (2026-10-20): Ian allowed the agent to create core/contracts/ for Phase 0
step 2. One time, new files only; core/budget.py and tests/spec/ untouched.
Contract defaults approved: evidence_event_ids always non-empty; freeze frame up
to 22 players (max 11 per team, sent-off players absent); importance and
confidence 0..1; risk_tier low|medium|high; overlay text needs 'en'.

Exception (2026-10-20): Ian allowed the agent to edit core/contracts/event.py once,
to add facing_deg. Conventions: facing_deg 0 = +x, anticlockwise, [0, 360),
required; SPADL coordinates, acting team attacks x=105 (own goal at x=0).

Idea for later (engine knob, Ian to decide): weather (rain, wind) affecting play,
e.g. rain slows passes and raises the error rate.

Exception (2026-10-20): Ian allowed the agent to edit core/contracts/match.py once,
to add weather (dry | rain | wind | heat), required, schema_version stays 1.

Phase 1a (2026-10-20): the engine sets under_pressure with Ian's rule only:
at least one opponent within 2 m. The full pressure formula waits for Phase 2.
League: 7 placeholder clubs + engine/league/clubs/_template.yaml for Ian's club.

Phase 1b (2026-10-20), Ian's answers: Riverside Athletic is the 8th club.
In possession with the ball on the left, the far-side CM (RCM) joins the front
five and the LCM stays in the base two with the DM. Out of possession, the
ball-side CM steps up beside the 9 (left CM when the ball is central).
Demo match: Riverside Athletic v Ironvale, dry, 15:00 Nairobi time.
Defaults chosen by the agent (check the PNGs in docs/shapes/): in-possession
centre = halfway between left and right; transition = halfway between in and
out of possession, used by both teams for 5 s after a turnover.

Exception (2026-10-21): Ian allowed the agent to edit core/contracts/match.py once,
to add mode ("scenario" | "free_simulation"), required. Scenario matches are
scripted and must be labelled "scenario" in the UI.

Phase 1c (2026-10-21), Ian: opponent Harbour Town; demo scenario ends 0-2
(Harbour's third counter behind Riverside's left-back at 88' replaces the
1-1 equaliser). The demo match is now this scenario (was Riverside v Ironvale).

Phase 1d realism tuning (2026-10-21), engine/config/engine.yaml, before -> after.
Tuned on 500 matches (seeds 10000-10499) against 2024/25 top-five-league bands
(evals/realism/reference.yaml); checked on unseen seeds 50000-50499.
- shots.bias: 1.5 -> 2.42 (shots/match 18.8 -> 24.5; band 23.7-25.9)
- xg_model.intercept: -1.4 -> -1.45 (keep goals ~2.9 and xG/shot ~0.117)
- shots.save_share: 0.45 -> 0.27 (on-target share 0.52 -> 0.35; band 0.34-0.38)
- failed_pass.interception: 0.5 -> 0.18, tackle: 0.25 -> 0.08,
  loose_ball: 0.25 -> 0.77 (PPDA 5.6 -> 12.5; band 11.2-13.1)
- pressing.counterpress_regain: 0.25 -> 0.15 (same reason: fewer ball wins)
- challenges.foul: 0.12 -> 0.46 (fouls/match 10.6 -> 22.5; band 21.4-25.0)
- challenges.yellow_per_foul: 0.12 -> 0.185 (yellows 1.2 -> 4.1; band 3.7-4.5)
- challenges.red_per_foul: 0.006 -> 0.008 (reds 0.05 -> ~0.17; band 0.14-0.21)
Red cards cannot strictly pass at 500 matches: they are rare, so the 95%
interval is about as wide as the real band. The mean sits in the band.

Blind analyser (2026-10-21, Ian): events carry only what a real feed has
(xg, assist, length_m). Engine-only labels (counter, channel, last_man,
lines_broken, scenario_beat, and the new mode/threat) live in an engine-truth
sidecar used only by evals. core/, stream/ and agents/ may not import the
engine. Reason: otherwise the moment detector could read the answer key and
evals would be circular.

Phase 1e game state (2026-10-21, Ian). engine/config/engine.yaml game_state;
all TUNABLE, owner Ian. Replaces the old late_minute 70 / leading_press /
trailing_* rules.
- From 65': leader by 1-3 "manages" (press a step lower, slower, slightly
  safer passing, not deep); escalates to "protect" (club's late_lead_block_drop,
  counters, shape_when_protecting_lead) when the opponent's share of the last
  5 min with the ball in the leader's defensive third >= 0.35 (>= 0.25 vs a
  stronger opponent, by club strength). Back to "manage" only after < 0.20 for
  5 consecutive minutes; threat-driven switches at most once per 5 minutes.
- Trailing by 1-2 from 65': "chase" (faster, presses more, full-backs higher,
  more shots, shape_when_chasing). Lead of 4+: normal style.
- 3-goal lead: Ian first said "like comfortable", then the addendum made it
  "manage, then react" from 65'. The addendum stands.
- Red card: most advanced player fills the gap, then shape_after_red_card
  from the club YAML if given (Riverside 4-4-1).
- Club strength 0-1 added to every club (placeholders).
- Agent's tuning of mode effects: "safer passing" alone made leaders keep MORE
  of the ball, so manage presses much less (x0.55) and chasers press more
  (x1.35) and are not more direct. Result on 400 matches: one-goal leaders give
  up ~4 points of possession after 65'; level teams 0.

Phase 1e club identity + re-tuning (2026-10-21), engine/config/engine.yaml,
before (main) -> after. All TUNABLE, owner Ian. Agent's changes, each with why:
- New mechanics: long balls contested (long_from_m 30, long_per_metre 0.08);
  final third: every team combines (final_third_directness 0.35); possession
  teams recycle short (safe_pass_bonus 4); past its usual passes a team goes
  long (go_long_directness 0.95, go_long_backward 0.2); every club counters
  after winning the ball with p = 0.6 x directness (direct_counter); direct
  teams shoot more readily (direct_shot_bonus 1.5); attacking runs: in
  2-striker shapes midfielders push up from x 30 (attack_runs share 0.85,
  scaled down for shapes with more forwards); defences crowd their own box
  (deep_zone_x 80, deep_zone_press 5); better clubs keep the ball better
  outside the final third (pass_model.per_strength 4).
  Why: long-ball clubs took ~4 shots/match and kept ~52% possession.
- pass_model.intercept 3.9 -> 4.75, passer_pressure 0.9 -> 1.8,
  receiver_pressure 1.2 -> 2.0 (pressure ends possessions; completion back to 83%)
- xg_model.intercept -1.45 -> -1.25 (xG/shot 0.118, goals 2.8)
- shots.bias 2.42 -> 1.65 (shots 24.3/match)
- failed_pass.interception 0.18 -> 0.27 (PPDA 12.5)
- challenges.foul 0.46 -> 0.42, yellow_per_foul 0.185 -> 0.17,
  red_per_foul 0.008 -> 0.0075 (fouls 23, yellows 4.0, reds ~0.17)
Result (docs/DATA_REALISM.md): 10 of 13 pass on tuning seeds, 8 of 13 on
hold-out. Possession spread 0.048 vs real 0.057-0.076 still fails: the
fictional clubs' placeholder strengths/styles are close together.
Test change: Harbour v Saltmere no longer has channel balls by Harbour only
(every club now counters by directness); the test now requires Harbour to do
it at least 3x as often (127 vs 31 over four matches).
Reference: possession, pass completion, passes per match and per-team shots
now have sources (ESPN public match summaries, an unofficial API; and
football-data.co.uk per-team shots).

Club strength spread (2026-10-22, Ian delegated the call to the agent): tried
wider placeholder strengths (0.30-0.85). Possession spread reached the band
edge (0.058) but the gap between clubs' shots grew to 12-13 (real 6.3-9.4),
because weak direct clubs fell to ~6 shots. Kept the current ratings
(0.40-0.75): 10/13 realism metrics pass; possession spread (0.048) stays a
known gap. Proper fix needs an underdog chance mechanism (counters, set
pieces), to revisit once Phase 2 metrics show where chances come from.

Style clubs + set pieces (2026-10-22, Ian).
- Three fictional clubs in famous styles (invented names, no real clubs or
  players): Kingsbridge Ravens (Conte-style 3-4-3 / 5-4-1, 2016/17), Westmarch
  FC (Guardiola-style high press, 2017/18), Thornfield Athletic (Arteta-style
  control + set pieces, 2025/26). League is now 13 clubs.
- Set pieces per club (threat, foul_drawing, corner_seeking; defaults 0.5 /
  0.3 / 0.3). Threat order: Thornfield > Kingsbridge > Westmarch. Mid-table
  "fouls and corners" clubs (agent's pick of existing clubs): Port Ilvane,
  Tidewick. Corners now also come from failed crosses and deflected shots;
  wide final-third free kicks are crossed in.
- Late game (Ian): from 85' a leading team wins more fouls in the final third,
  takes its time, and always puts those free kicks into the box.
- Club strength is now relative to the league (pass_model.strength_centre
  0.63 = mean strength), so adding strong clubs does not raise everyone's
  passing. Knobs, before -> after: pass_model.intercept 4.75 -> 5.25,
  challenges.foul 0.42 -> 0.36 (fouls are now drawn more in the final third),
  red_per_foul 0.0075 -> 0.0065, shots.bias 1.65 -> 1.8; new set_pieces block
  (corners 9.6/match vs real 9.3-10.3).
- Known: Westmarch (very patient) under-shoots for a Guardiola-style side
  (13 shots, 1.45 goals/match); Ian to decide whether to make it more direct.
- Test change: "4-goal leaders change less than 1-goal leaders" now uses 200
  strong-v-weak fixtures (both groups from the same set, min 20 teams each);
  with 13 clubs a general 200-match sample had only 8 such teams. Checked on
  800 general matches: drop 0.030 (1 goal) vs 0.018 (4+ goals).
