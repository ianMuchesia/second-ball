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
make replay MATCH=demo SPEED=10                                  # demo through Kafka -> live metrics -> docs/timelines/demo.png
```

See [docs/DATASHEET.md](docs/DATASHEET.md) and [docs/DATA_REALISM.md](docs/DATA_REALISM.md).

## Live narration

```sh
make live MATCH=demo SPEED=10     # replay -> Kafka -> moments -> agents -> overlays (topic + docs/overlays/)
make jaeger                       # then OTEL_EXPORTER=otlp: one trace per moment at http://localhost:16686
make narrate                      # the demo's big moments through the model in .env
make eval-narration eval-latency  # repeat-run rates and p50/p95 per stage -> docs/EVAL.md
```

Code computes every number; agents only choose words, and a code Verifier
checks every line before it can air. It catches what a number check alone
misses: **the right number on the wrong team** ("Harbour's control 0.80"
when the 0.80 is Riverside's), the wrong team said to be leading, counts in
words ("one pass", "second counter goal") that the events do not show,
"halved" when the change is not about half, decimals in a fan's line, soft
predictions ("seal it") while the clock runs, and translations that change a
number. Rejected drafts are kept with their reasons. If the model is slow,
down or over budget, a code template airs instead: never an empty overlay.
Details: [agents/README.md](agents/README.md).

## Broadcast screen (Phase 4a)

```sh
make record MATCH=demo            # the pipeline once -> runs/demo/ (model from .env; EN + SW)
cd web && npm run build && cd ..  # the screen
make api                          # http://localhost:8000/runs/demo  (judge mode: 0 model calls)
make e2e                          # Playwright smoke test on a fake-model bundle
```

The screen (React + TypeScript, Redux Toolkit + RTK Query, React Router with
lazy routes) plays a recorded run: scoreboard, 2D pitch with the ball path and
name tags, timeline markers, the lower-third line (fan or analyst, English or
Kiswahili), and only three indicators (control, openness, momentum) with their
registry definitions. **Why?** opens the evidence: the claim, the Verifier's
verdict with any rejected drafts, the events in plain words, the rule or
metric, and the pitch jumps to the moment with the players lit. The Producer
tab shows lines waiting for approval, the real rejected drafts, an
append-only audit log, and a clearly labelled "Inject a test error". Every
line shows how long it really took (target: 8 s).

Rules for coding agents: [AGENTS.md](AGENTS.md). Decisions: [DECISIONS.md](DECISIONS.md).
