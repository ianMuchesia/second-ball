# engine

Synthetic match generator. Fictional clubs, invented players, synthetic data only.

```sh
uv run python -m engine.generate --home ashgrove --away ironvale --seed 1 --weather rain > match.jsonl
```

Same seed = identical match. Output is `Match` then one `MatchEvent` per line
(`core/contracts`), in the SPADL frame: the acting team attacks towards x = 105.

| Path | What |
|---|---|
| `league/clubs/*.yaml` | 8 club style profiles, incl. Ian's `riverside_athletic.yaml`. Files starting with `_` are ignored. |
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
