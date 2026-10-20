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
