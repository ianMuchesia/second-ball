# second-ball

Monorepo. No features yet.

| Path | What |
|---|---|
| `engine/` | synthetic match generator |
| `core/` | red zone: metric definitions, moment rules, verifier, approval policy, budget |
| `stream/` | replayer + interpreter service |
| `agents/` | agents + football MCP server |
| `web/` | broadcast screen (React + TypeScript, Vite) |
| `evals/` | gold set, harness, promotion gate |
| `infra/` | Bicep |
| `docs/` | RFC, DATA_REALISM, EVAL, SECURITY, COST |

## Run

```sh
cp .env.example .env   # set PG_PASSWORD
uv sync
make up                # Kafka on :9092, Postgres on :5434
make lint test
cd web && npm ci && npm run dev
```

## Data

```sh
uv run secondball generate --matches 100 --seed 7 --out data/   # synthetic dataset
make demo                                                        # scripted demo scenario
make realism                                                     # realism report vs real leagues
```

See [docs/DATASHEET.md](docs/DATASHEET.md) and [docs/DATA_REALISM.md](docs/DATA_REALISM.md).

Rules for coding agents: [AGENTS.md](AGENTS.md). Decisions: [DECISIONS.md](DECISIONS.md).
