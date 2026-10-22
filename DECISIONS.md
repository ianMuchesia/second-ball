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

Phase 2a: replayer, interpreter, metric registry (2026-10-21).
- Permission exception (Ian): the agent may create core/metrics/ (new files
  only; budget.py and core/contracts untouched).
- Dedupe store (Ian): Postgres. Each event is inserted with event_id as the
  primary key before it is counted; the Kafka offset is committed after. A
  restart rebuilds MatchState from the stored events. Stream tests start
  throwaway Kafka/Postgres containers (CI: services).
- New dependencies: confluent-kafka (Kafka client; also speaks the Azure Event
  Hubs Kafka endpoint via SASL_SSL), psycopg[binary] (Postgres for the store).
- Metric definitions (agent's, for Ian to review; one place each in
  core/metrics/basic.py):
  - Possession owner = first team on the ball in a possession_id; the tackle,
    interception or foul that ends it belongs to the other side.
  - Possession (time) = share of in-play time; gaps before a restart, after a
    goal and across half-time are not in play.
  - Passes exclude throw-ins (same set as the realism report). PPDA uses the
    realism report's zone (the passer's own 60%).
  - Field tilt = share of final-third passes (x >= 70 in each team's frame).
  - Windows (5/10/15 min) run on a continuous match clock: first-half
    stoppage time counts, so early second-half windows reach into it.
  - A metric that is undefined (PPDA with no defensive actions) is left out of
    MatchState rather than shown as 0 or infinity. A zero (no shots) carries
    the events that were checked as evidence.
- MatchState.metrics keys: team_id or "match" (match-grain metrics); windowed
  metrics are named "<metric>_last_<n>m". No contract change.
- Latency at 60x: p50 ~0.02 s, max 0.07 s. The first events once paid Kafka
  start-up (consumer group join, up to 5 s via make replay); the replayer now
  connects before the match clock starts and, with --wait-for-group, starts
  only once the interpreter has its partition. The test waits for the
  assignment too (limit unchanged: every event < 1 s).
- Timeline: docs/timelines/demo.png is committed; the CSV next to it is data
  (git-ignored, *.csv).

Phase 2b: control and chaos metrics (2026-10-21, Ian via the advisor's prompt).
- Ian's definition of chaos (Argentina-France): an *open* match, both teams
  creating, attack after attack. That is "openness"; "scrappiness" (ball
  changing hands in midfield) is kept as a secondary, analyst-only group.
  Metrics describe; they never call a match good or bad (tested).
- Contract change (Ian's instruction in the 2b addendum): Match gets
  home_strength / away_strength, public pre-match ratings (0-1). Rule: what a
  broadcaster knows before or during a match is fair; the simulator's hidden
  workings (mode, threat signal) are not.
- Engine (addendum), TUNABLE: technical quality (quality.*) makes weaker
  clubs lose more passes, receptions and take-ons under pressure; underdog
  caution (underdog.*) grows with the strength gap: deeper block, fewer
  attacking runs. (An extra "underdogs counter more" knob was tried and
  removed: with it, 4-goal leaders changed more than 1-goal leaders, breaking
  Ian's game-state rule test.)
  Knobs, before -> after: xg_model.intercept -1.25 -> -1.3 (goals back in band).
  Effect on realism: possession spread now PASSES (0.061, was 0.053); the
  gap in shots between the best and worst club widened (team_shots_range
  ~13 vs real 6.3-9.4; was 10.4). Tried lowering pass_model.per_strength and
  an underdog counter boost: goals rose out of band and the gap stayed ~13.
  Ian to decide whether weak clubs should shoot more.
- field_tilt is now final-third *touches* (2b spec), not passes.
- xT: 16 x 12 grid, value iteration on 500 free_simulation matches (seeds
  70000+), moves = successful pass/cross/dribble/take-on; artifact
  core/metrics/artifacts/xt_v1.json (versioned; records seeds and an engine
  config hash). Re-fit with `uv run python -m scripts.fit_metrics`.
- Openness scales (core/metrics/config.yaml) set near the 90th percentile of
  10-minute windows in 500 free matches: two-way threat 0.2 xG, 4 threat
  switches, transition 6 s (fast) to 40 s (slow). Threat = shot or ball at
  xT > 0.05. Baseline per strength-gap bucket in
  core/metrics/artifacts/openness_baseline_v1.json (seeds 80000+):
  <0.1: 0.369, 0.1-0.3: 0.351, >0.3: 0.337 (window sd ~0.19, so the fixture
  effect is real but small; most variation is within matches).
- openness_vs_expected = openness minus the bucket mean (difference, 0-1 units).
- Control index = equal-weight mean of possession (time), field tilt, xT share.
- Windows: control and openness on rolling 10 minutes only; xT share and
  scrappiness also whole-match.
- Demo late spell (Ian, 2026-10-22): after the engine changes, 80-88' in the
  demo was no longer open (Riverside, 10 men, chased but barely created).
  Ian's decision: (1) script it: two labelled beats, counter_chance_82
  (Riverside) and counter_chance_85 (Harbour), plus an open_spell moment in the
  answer key; (2) replace the single-demo test with a general one over 300
  free matches: two-way threat in late chasing spells (margin 1, 75'+,
  trailing team in chase mode) vs the same matches' 0-30' windows; if it
  fails, report, do not tune. Result on the final engine: +0.032 xG (95% CI
  +0.021 to +0.044, n=170 matches): PASS. A "chasing teams throw players
  forward" knob was tried (+0.044) but removed, since the rule holds without
  it and nobody asked for it.
- Test precision fix: "4-goal leaders never manage or protect" compared a
  mode switch's exact time with a goal's whole-second event time, so a switch
  just before a goal in the same second looked like it came after. The engine
  now logs how many events came before each switch, and the test uses event
  order. Same rule, exact instead of rounded.
- Test changes: field-tilt test now checks touches (definition changed by the
  spec, value unchanged, evidence check added); the registry test allows
  analyst-only metrics (scrappiness has no casual name, per the spec).

Phase 2c: remaining metrics (2026-10-22, Ian via the advisor's prompt).
- Contract: MetricValue gets optional numerator/denominator; every rate
  fills them (for Wilson intervals later).
- Overload: Ian chose his own approved version (box 20 m ahead / 10 m back in
  the ball's lane, recovering defenders count, danger by place), not the
  prompt's 15 m circle.
- Pass difficulty weights (Ian, 2026-10-22): passer pressure 25, lines broken
  25, zone 15, receiver pressure 15, distance 15, forwardness 5. Zone is Ian's
  addition ("near their box passing is much harder"). See
  docs/metrics/pass_difficulty.md.
- Pressure (Ian's answers): weight 1 within 2 m, straight line to 0.2 at
  5 m; x2 in front of where he faces OR goal-side (x > his x), x2 once even
  when both; pressure = min(1, sum / 2), so one close opponent = 0.5.
- Agent's readings of the spec, for Ian to review:
  - Risk = exp(-(distance to own goal / 40 m)^2): ~0.66 at the box corner,
    0.18 at halfway; in the final third ~0 when the team has the upper hand
    (last 10 min), no outfield defender is goal-side, or it has an overload.
  - The keeper is not in the feed: "keeper" = the player nearest his own goal.
  - Upper hand without any defender touches in their own third = no
    "constant pressure" shown = no upper hand. Value 0 / 1 / 2 (strong).
  - Lines: defenders' outfield x split at the largest gaps into up to 3 lines.
  - "Pressures" (no pressure events in the feed) = opponent touches in their
    own third made under pressure.
  - Counter-press regain: timed from the ball lost to the tackle or
    interception that won it back (not the next touch).
- On the demo: seconds between actions is flat at 3 s (the engine stamps
  whole seconds); name tags fire often for direct teams (40 m passes are
  common); both are dials for Ian.
- Display names never judge: Ian's rule name stays `bad_situation` in code;
  on screen it is "Danger on the ball".
- Flaky CI fix: test_latency_under_one_second_at_60x failed once on GitHub
  (max 1.135 s) on the 2b merge and passed on a rerun of the same commit.
  Cause: the interpreter wrote the full MatchState (~1 MB at full time) to
  Postgres after every event. The live state still updates per event; the
  Postgres copy is now saved at most once a second and always at MatchEnd
  (a restart rebuilds from stored events, so correctness is unchanged).
  Pinned to one CPU core: max latency 0.331 s per-event saving -> 0.132 s
  throttled. Limit unchanged (every event < 1 s); the test also checks that
  saves are throttled.

Phase 3a: moments + MCP server (2026-10-22, Ian).
- Models: Gemini for development (via the agents/llm adapter); production on
  Azure Foundry because Stage One checks the required Microsoft technologies
  and judges score Foundry: gpt-5-mini for the Analyst (reasoning effort low),
  gpt-4.1-mini for the Narrator and Localizer. No local Qwen backup: when a
  model fails, the fallback is a plain template sentence (safer and free).
- Azure region: southafricanorth. The student policy allows 5 regions; only
  South Africa North, UAE North and Spain Central offer Foundry models; SAN
  is closest to Nairobi. Deployment type GlobalStandard: synthetic data only,
  so global processing is acceptable.
- Name tags: passes of 45 m+ (was 40), never goal kicks or the keeper's long
  kicks (clearances never counted as passes); shots 100 km/h+; at most one
  tag per player per 5 minutes.
- Contract: Moment gets `team` (None = match-wide) and `clock` (when it fired).
- Eval matching (Ian): the demo answer key's kinds map to detector kinds:
  control_rising / control_drop / field_tilt -> control_shift;
  chaos_rising / open_spell -> openness_spike; chance -> big_chance;
  block_drop -> shape_change; counter_behind_fullback -> big_chance or
  repeated_pattern; goal, repeated_pattern, red_card_impact, shape_change,
  pressure_spike -> same name.
- Homework note: in the demo, 88' is Harbour's second counter goal (0-2), not
  an equaliser.

Phase 3b-1 A: answer key and detector (2026-10-22, Ian via the advisor).
- Answer key: "Riverside lose control after the red card" was wrong (control
  rose 0.71 -> 0.80: a 10-man side chasing often has more of the ball; the
  danger changes, not possession). Replaced by counter_threat_rising (Harbour,
  63-80') -> detector kinds big_chance / repeated_pattern. Block drop window
  80-88' -> 65-85' (gradual from the 65' game-state rule). 88' noted as
  Harbour's 2nd counter goal behind the left-back, final 0-2.
- Control: no control moment before 10'. From 15', control_shift also fires
  when a team's control (last 10 min) is >= 1 sd above the usual for its
  fixture (new artifact control_baseline_v1.json: control by team strength
  minus opponent strength, same 500 free matches as the openness baseline).
  Riverside's usual in the demo fixture: 0.70; fired at 24' (0.84).
- Block drop: two-sided CUSUM on each team's per-minute back-line depth (ball
  in the middle third) against its own earlier average; fires once per
  direction until the drift is gone. Demo: Harbour's drop confirmed at 75'.
- Hysteresis (like Ian's game-state rule): a control-vs-fixture moment stays
  "on" until control falls below 0.5 sd above usual; a window shape change
  until the change falls below half its thresholds. Without it, a value
  hovering at the line re-fired every 3 minutes (one free match hit 1.0
  moments per minute and failed the spam test).
- Eval after the fixes: demo recall 19/19 (Wilson 83-100%), precision 19/44
  = 43% (the key lists the story's big moments only); free matches 64 moments
  per match.

Phase 3b-1 B: narration pipeline with a fake model (2026-10-22).
- Framework: Microsoft Agent Framework, `agent-framework-core` 1.22 (the core
  package, not the full bundle of integrations). New dependency, why: the
  brief scores Microsoft agent technology; agents + a typed workflow with a
  retry edge. Models sit behind our adapter (AdapterChatClient), so every
  call still passes core/budget.py.
- New LLM provider "fake" (price 0, still charged through the budget):
  deterministic, with error injection for tests.
- Verifier is code. Agent's choices, for Ian to review: numbers match with
  the line's own rounding (0.7 or 71% for 0.712); allowed context numbers =
  score, current and moment minute, shirt numbers and player counts on the
  pitch; any capitalised word that is not a team, a player on the pitch or in
  a list of common words counts as a name (sentence starts included: the
  Verifier would rather retry than air an invented player);
  injury/referee words -> risk tier high (needs a human), not a rejection.
- Producer times are match seconds; Ian/advisor's 8 s freshness and 45 s gap
  are viewer seconds, so both scale with replay speed (x10 at 10x).
- Localizer: target language Swahili ("sw") by default (agent's assumption
  for a Nairobi audience; Ian to confirm). A translation whose numbers differ
  from the English line is dropped; English always airs.
- Narrator examples: placeholder file agents/narrator/examples.yaml; Ian
  writes the six lines.

## 2026-10-22: real model (Gemini) and Ian's narrator lines

- Narrator examples: Ian's six lines (second version, his own pick; "lightning"
  added to the Verifier's common words so his 34' opener is not taken for a
  name). Earlier draft: drafted with Gemini, picked and trimmed
  to the 25-word limit by the agent). They are gold items: a test runs each
  through the Verifier against the real demo moment.
- Gemini rate limits are per project, per minute and per day (numbers in AI
  Studio; https://ai.google.dev/gemini-api/docs/rate-limits). Over the limit
  -> 429. Guards: our own pacing (GEMINI_RPM, default 10 a minute, safe on
  the free tier) and SDK retries on 429/503 (4 tries, 2-30 s backoff; the
  SDK does not retry by default).
- Budget precheck token count is local (1 token per UTF-8 byte, about 3x the
  real count on our prompts, so stricter) instead of the count_tokens API:
  that call was a second request per model call (half the RPM cap) and took
  about 6 s. The charge still uses the real usage from the answer.
- `make narrate` / scripts/narrate_demo.py: demo moments with importance >= 0.9
  through the real pipeline. First run: 3 moments x 2 personas, 18 calls,
  every line passed first try, $0.0033, 1 min 46 s at 10 requests a minute.

## 2026-10-22: who is winning, copies, untranslated Swahili (advisor's 3 fixes)

- Prompt VALUES now carry code-made words: "standing" per team (leading /
  trailing / level, "a player down"), "event" ("Riverside had a player sent
  off"), "good_for" (red card helps the opponent; a goal helps the scorer)
  and "numbers_are_for" (whose metrics). Before, the model read the red card
  as good for Riverside and gave Riverside's control numbers to Harbour.
- Verifier rejects a line that says the wrong team leads or trails ("X
  lead", "X trailing", "leading X"), checked against the score.
- Verifier rejects a line too close to a style example (word overlap,
  Jaccard > 0.8); the examples are labelled "STYLE EXAMPLES ONLY - DO NOT
  COPY". The gold test checks Ian's lines without this check (they are the
  examples).
- Localizer: a reply that is the English line, has 2+ common English words
  (the, and, behind, from, with, their, again, is) or changes a number gets
  one retry with the reason, then the language is dropped (English airs).
  The prompt says "clinical" is the football sense (it came back as
  "kimatibabu", medical).
- Real run after the fixes: all lines right about who leads and who the red
  card helps; one invented number (0.45 = 1.73 - 1.28) caught and retried.

## 2026-10-22: goals linked to the counter pattern; soft predictions

- agents/pipeline/facts.py: a goal "came from a counter behind the
  full-back" only if the move that ended in it passes the detector's own
  counter rule (core.moments, reused as is, not copied; core/ untouched).
  Facts reach the prompt (build_up, exploited_zone, and "second counter goal
  ... in this match"); the Verifier then requires the line to name the
  counter and the side; the fallback names them too. Demo: both goals,
  behind Riverside's left-back. 30 free matches: 3 of 90 goals (3%), so the
  label is rare.
- Verifier rejects soft predictions (seal it, secure the 0-2, game over, put
  it beyond doubt, clinch the win ...); "make it 0-2" is allowed.
- Verifier rejects one team's control/xG/threat/momentum given to the other
  (pressure is left out: Harbour apply the pressure on Riverside's ball).
- Leader check reads only clear forms ("Harbour lead", "Harbour are
  trailing"), not a bare participle after a team that is an object, and not
  "behind" (space). Verdicts keep the draft text, for evals and debugging.

## 2026-10-22: Phase 3b-3 (number words, personas, four languages, repeat runs)

- Red card facts from events (agents/pipeline/facts.py): who (shirt number;
  the feed has no names or positions, so not "centre-back") and why. "On a
  counter" = the fouled team won the ball in its own half, went >= 15 m
  forward and was fouled within 10 s (the detector's counter thresholds).
  "Last-man" = no other outfield player of the fouling team goal-side of the
  foul (Ian's pick). Demo: "foul on a counter", NOT last-man: two Riverside
  defenders (numbers 2 and 4) were goal-side. The scenario action
  red_card_last_man does not place the defenders to match: engine gap,
  reported to Ian, not tuned. The Insight claim for a red card is code's.
- Number words: counts before a football noun ("one pass", "ten men",
  "second counter goal", "twice") must match a code-made count of that kind
  (passes in the move, 11 - red cards, goals, counter goals/counters, cards).
  "once" is not checked ("once more" means again). Comparisons (halved,
  doubled, up/down by a third, up by half) must be within 10% of a real
  before/after ratio (Ian's pick).
- Personas: casual lines carry no decimals; their prompt has the registry's
  casual names with the team in place of "they" ("How much Riverside are
  being pressed": "halved"), and the change words computed in code. Analyst
  prompt has values plus units.
- Localizer: French, Spanish, Swahili, Arabic (Arabic right-to-left in the
  UI). Team names, scores, numbers and xG are locked as typed tokens ([T1],
  [S1], [N1], [X1]); a reply must keep every token once and add no digits;
  then the number check and the not-English check run on the translation.
  Number words inside a translation (e.g. Arabic) are not checked yet.
- Repeat runs (evals/narration/report.py, "narration" section of
  docs/EVAL.md, shared with the moments report by markers): free tier, 10
  requests/min, 10 runs English + 2 translation runs. The full 20-run report
  runs on the Foundry models in Phase 6: eval numbers belong to the model that
  produced them.
- More soft predictions: knockout blow, killer blow, nail in the coffin,
  coup de grace.
