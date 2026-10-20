# engine

Synthetic match generator. Fictional clubs, invented players, synthetic data only.

```sh
uv run python -m engine.generate --home ashgrove --away ironvale --seed 1 --weather rain > match.jsonl
```

Same seed = identical match. Output is `Match` then one `MatchEvent` per line
(`core/contracts`), in the SPADL frame: the acting team attacks towards x = 105.

| Path | What |
|---|---|
| `league/clubs/*.yaml` | 7 club style profiles. `_template.yaml` is for Ian's club (ignored until copied). |
| `config/weather.yaml` | weather multipliers |
| `config/engine.yaml` | engine mechanics: pass model, xG, pressing, cards, game state |
| `core/` | possession-chain state machine, shapes and freeze frames |

Every number in the YAML files is **TUNABLE (owner: Ian)**.

`under_pressure` uses Ian's rule: at least one opponent within 2 m. The engine's
own pressure load (`engine/core/models.py`) drives the simulation only; it is
not the pressure metric, which comes in Phase 2.
