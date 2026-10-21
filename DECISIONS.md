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
