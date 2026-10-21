# Datasheet: second-ball synthetic football data

What this dataset is, how it was made, and what it cannot tell you.

## In one paragraph

Event data for **fictional** football matches, with the positions and facing
direction of every player at every event. A seeded simulation engine generates
it. No real clubs, players, matches or personal data are in it. It is meant
for building and testing match-analysis tools (metrics, moment detection,
commentary), not for analysing real football.

## How to make it

```sh
uv run secondball generate --matches 100 --seed 7 --out data/
uv run secondball generate --matches 100 --seed 7 --out data/ --no-jsonl   # Parquet only
uv run secondball generate --matches 100 --seed 7 --out data/ --weather mixed
```

Same arguments = same data, byte for byte in content. Match *i* uses seed
`seed + i`; fixtures cycle through every ordered pair of the league's clubs.
`data/` is git-ignored: generated data is never committed.

## Files

| File | One row / line per | Notes |
|---|---|---|
| `matches.parquet` | match | contract `Match` fields + `home_goals`, `away_goals`, `events` |
| `events.parquet` | event | contract `MatchEvent` fields; `freeze_frame` is a nested list; `qualifiers` is a JSON string |
| `jsonl/<match_id>.jsonl` | `Match`, then each `MatchEvent` | exactly the contract JSON (`docs/schemas/`) |
| `engine_truth.parquet` | labelled event | engine-only labels (evals only, never the analyser) |
| `manifest.json` | dataset | arguments, counts, clubs, schema version |

Size: about 1,450 events per match. 100 matches ≈ 30 MB Parquet, ≈ 340 MB JSONL.

## Schema (short)

Full JSON Schema: `docs/schemas/` (generated from `core/contracts`).

- **Coordinates:** metres on a 105 × 68 pitch, SPADL convention: each event is
  in the **acting team's frame**, attacking towards x = 105 (own goal at x = 0).
  Left touchline is y = 68. Rounded to the centimetre.
- **Event types and outcomes:** SPADL action types (pass, cross, dribble = carry,
  take_on, shot, tackle, interception, foul, keeper_save, ...) and results
  (success, fail, yellow_card, red_card, ...).
- **freeze_frame:** every player on the pitch (22, or fewer after red cards):
  `player_id`, `team_id`, `x`, `y`, `facing_deg` (0 = +x, anticlockwise, 0.1° steps).
- **under_pressure:** at least one opponent within 2 m of the acting player in
  the stored freeze frame (Ian's rule; `core` metric definitions come in Phase 2).
- **qualifiers:** only what a real event feed carries: `xg` (the engine's own
  xG model), `assist` (pass type before a shot) and `length_m`.
- **Engine truth (separate file):** labels only the engine knows (`counter`,
  `channel`, `last_man`, `lines_broken`, `scenario_beat`) are in
  `engine_truth.parquet` / `engine_truth.jsonl`, keyed by `event_id`. They are
  for evals only: the analyser (core/, stream/, agents/) works from events alone,
  so it cannot "detect" a moment by reading the answer.

## How it was made

- **Engine:** a possession-chain state machine (`engine/core/`). Each step the
  ball carrier chooses pass / carry / take-on / shot / clearance from the zone,
  the club's style and pressure. Pass success and shot xG are logistic models;
  failed passes become interceptions, tackles or loose balls; late in the game
  leading teams drop deeper, trailing teams speed up, fatigue lowers pressing.
- **Clubs:** 10 fictional clubs with style knobs (`engine/league/clubs/`),
  including Ian's Riverside Athletic and Kilele Chui FC.
- **Shapes:** players stand on formation anchors per phase (with / without the
  ball / transition) and ball side, and move half-way towards them each event.
- **Calibration:** knobs were tuned so league and per-team averages fall
  inside real 2024/25 top-five-league bands (football-data.co.uk, Understat,
  ESPN match summaries); see `docs/DATA_REALISM.md` and `DECISIONS.md`.
- **Clubs** have a strength rating (0-1): better clubs keep the ball better.

## Free simulation vs scenario

- `secondball generate` only makes **free_simulation** matches: the engine
  alone decides what happens.
- **Scenario** matches (`engine/scenarios/`, e.g. `make demo`) are **scripted**:
  goals, red cards and some counters happen at set minutes. They carry
  `mode: "scenario"` on the `Match`, `scenario_beat` in the engine-truth file
  for scripted events, and an `expected_moments.json` answer key. Never present a scenario as a natural
  outcome of the engine.

## Known limits

- **Not real football.** Players have no individual skill, speed or stamina;
  the ball travels instantly along straight lines; there are no penalties,
  offsides, substitutions or injuries.
- **Possession spread is too narrow.** Clubs range about 42–60% possession;
  real leagues spread wider (see `docs/DATA_REALISM.md`). Shots per club are
  now realistic on average, and the gap between clubs is at the top of the real range.
- **Match modes** (manage / protect / chase from 65', Ian's rules) change how
  teams play by score and minute; the modes themselves are engine-internal and
  never in the data.
- **xG** is the engine's own simple model, not a trained real-world model.
- **Red cards** are rare, so short samples vary a lot.
- **Freeze frames** are generated around the ball each event (anchors + noise +
  smoothing), not tracked continuously; movement between events is not modelled.

## Licence and contact

MIT (see `LICENSE`). Synthetic data only; any resemblance of club or player
names to real ones is accidental.
