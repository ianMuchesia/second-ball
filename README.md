# Second Ball

An AI broadcast companion for football: it watches a match as it happens,
notices what matters (a team taking control, a counter behind the same
full-back again, what a red card changes) and puts it on screen in plain
words, for a casual fan or an analyst, in English or Kiswahili.

**Code computes every number; agents only choose words.** A code Verifier
checks every line before it can air, and when the model is slow, down, over
budget or wrong three times, a code template airs instead. Every match, club
and player is synthetic.

## How it works

```
engine/  synthetic matches (seeded; a scripted demo story)  ->  events + 10 Hz movement
stream/  replayer -> Kafka -> interpreter                    ->  metrics each moment
core/    metric registry, moment rules, budget               ->  moments (code, no model)
agents/  Analyst -> Narrator -> Verifier (code) -> Localizer ->  verified lines + recaps
         Producer: risky lines wait for a human
web/     broadcast screen: 2D/3D pitch, lower third, evidence ("Why?"), Producer tab
```

| Path | What |
|---|---|
| `engine/` | synthetic match generator: clubs with their own styles, weather, game state, 10 Hz movement |
| `core/` | metric definitions, moment rules, budget and kill switch (changed only with Ian's approval) |
| `stream/` | replayer, interpreter and the broadcast API |
| `agents/` | the agents (Microsoft Agent Framework), the model adapter (`agents/llm`), the football MCP server |
| `web/` | broadcast screen (React + TypeScript, Vite) |
| `evals/` | moment, narration, latency and Verifier evals; the gold set |
| `docs/` | [EVAL](docs/EVAL.md), [COST](docs/COST.md), [SECURITY](docs/SECURITY.md), [DATASHEET](docs/DATASHEET.md), [DATA_REALISM](docs/DATA_REALISM.md) |

## Models

| Agent | Production (Azure AI Foundry, South Africa North) | Development |
|---|---|---|
| Analyst | gpt-5-mini, reasoning effort low, up to 1,500 output tokens | gemini-3.5-flash-lite |
| Narrator, Localizer, recaps | gpt-4.1-mini, up to 400 output tokens | gemini-3.5-flash-lite |

Every call goes through `core/budget.py`: a hard cap per run
(`MAX_RUN_USD`), a worst-case check before each call and a kill switch. Without
`--provider` every command uses a free fake model. A full recording of the
demo on Foundry costs about $0.03 ([COST.md](docs/COST.md)).

## Run it

```sh
uv sync
cd web && npm ci && npm run build && cd ..
make demo        # the scripted demo match -> demo/
make record      # the pipeline over it with the free fake model -> runs/demo-fake/
make api         # http://localhost:8000/runs/demo-fake  (judge mode: zero model calls)
make lint test   # see "Known issues"
```

With a real model (asks first, shows a request estimate from a free dry run):

```sh
cp .env.example .env    # FOUNDRY_ENDPOINT, FOUNDRY_API_KEY, FOUNDRY_MODEL,
                        # FOUNDRY_ANALYST_MODEL, MAX_RUN_USD (or GEMINI_API_KEY)
uv run python -m scripts.foundry_smoke                     # one tiny call per deployment
uv run python -m agents.live.record --provider foundry --out runs/my-run
```

The screen plays a recorded run: scoreboard, 2D or 3D pitch with the ball and
players, timeline, the lower-third line (fan or analyst, English or
Kiswahili) and three indicators (control, openness, momentum) with their
registry definitions. **Why?** opens the evidence: the claim, the Verifier's
verdict and any rejected drafts, the events in plain words, and the pitch at
that moment. The Producer tab shows lines waiting for approval, the real
rejected drafts and an append-only audit log. Every line shows how long it
took.

Live mode (Kafka, Postgres): `make up`, then
`make live MATCH=demo SPEED=10`; `make jaeger` for one trace per moment.

## What the Verifier catches

The right number on the wrong team ("Harbour's control 0.80" when it is
Riverside's), the wrong team said to be leading, counts the events do not show
("9 short passes"), "halved" when the change is not half, decimals in a fan's
line, predictions while the clock runs, unknown names, and translations that
change a number. On every draft it blocked in real runs, labelled by Ian: 14
real errors, all blocked for the right reason, and no false alarms
([EVAL.md](docs/EVAL.md)).

## Results (2026-10-25)

- Foundry recording of the demo: the Analyst answered 12 of 12 moments, 28 of
  28 lines written by the model, $0.032; p95 latency 12.6 s per line (the
  8 s target is not met yet).
- Moment detector: 15 of 19 expected story moments found in the demo.

Details, the promotion gate and the known gaps: [EVAL.md](docs/EVAL.md).

## Known issues

- `make test`: one known failure, the free-match moment spam check (1.04
  against 1.0). The sample-match speed test passes with a thin margin (4.7 s
  against 5 s).
- Free matches from the engine score too often (5.6 goals a match on average).
- Not deployed yet. The deployment is ready to run: `Dockerfile` (judge mode,
  one recorded run, no secrets, Producer writes off) and `infra/main.bicep`
  (Azure Container Apps); steps in [infra/README.md](infra/README.md). The
  public site plays a recording; live mode (Kafka, Postgres, real-time model
  calls) runs locally.

Rules for coding agents: [AGENTS.md](AGENTS.md). Decisions: [DECISIONS.md](DECISIONS.md).
