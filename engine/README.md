# engine

Synthetic match generator. Fictional clubs, invented players, synthetic data only.

```sh
uv run python -m engine.generate --home ashgrove --away ironvale --seed 1 --weather rain > match.jsonl
```

Same seed = identical match. Output is `Match` then one `MatchEvent` per line
(`core/contracts`), in the SPADL frame: the acting team attacks towards x = 105.

| Path | What |
|---|---|
| `league/clubs/*.yaml` | 13 club style profiles (incl. set pieces), incl. Ian's `riverside_athletic.yaml` and `kilele_chui.yaml`. Files starting with `_` are ignored. |
| `scenarios/*.yaml` | scripted scenarios (seed + beats + answer key) |
| `config/weather.yaml` | weather multipliers |
| `config/engine.yaml` | engine mechanics: pass model, xG, pressing, cards, game state |
| `core/` | possession-chain state machine, shapes and freeze frames |
| `../docs/shapes/` | PNG of every Riverside shape: `make shapes` |

## Shapes

Each club has a shape per (phase, ball side): phase is `in_possession`,
`out_of_possession` or `transition`; ball side is `left`, `centre` or `right`
in the team's own frame (left touchline = y 68). A club can write its shapes
in YAML (see Riverside); otherwise they come from its formation strings.
Right is always the mirror of left. Players move half-way towards their
current anchor each frame (`shapes.follow` in `config/engine.yaml`).

Every number in the YAML files is **TUNABLE (owner: Ian)**.

`under_pressure` uses Ian's rule: at least one opponent within 2 m. The engine's
own pressure load (`engine/core/models.py`) drives the simulation only; it is
not the pressure metric, which comes in Phase 2.

## Scenario mode (scripted)

`make demo` plays `scenarios/demo_riverside_harbour.yaml` and writes
`demo/match.jsonl` and `demo/expected_moments.json` (the answer key for evals).

A scenario is a seed plus **beats**: minute windows where the engine plays a
scripted sequence (a counter behind a full-back that scores or misses, a
last-man red card) or a modifier (a deeper block). Between beats the normal
engine runs, but it scores no goals and shows no red cards of its own, so the
final score is exactly the scripted one.

Honesty: scenario matches have `mode: "scenario"` on the `Match`, and every
scripted event is labelled `scenario_beat` in `engine_truth.jsonl`.

**Blind analyser:** events carry only feed qualifiers (`xg`, `assist`,
`length_m`). Engine-only labels go to the engine-truth sidecar, for evals only.
core/, stream/ and agents/ may not import the engine (tests enforce this). The UI must label them as
scenarios. Free matches have `mode: "free_simulation"`.
