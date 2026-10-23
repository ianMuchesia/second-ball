# agents

Agents interpret and narrate only; every number comes from code.

## Football MCP server (Phase 3a)

`agents/mcp_server/`: the only way agents get numbers. Read-only, typed tools
over one match; every value carries `evidence_event_ids`; no raw query tool.

| Tool | Returns |
|---|---|
| `get_metric(name, team, window)` | a registered metric now ("match" or a window in minutes) |
| `compare_windows(metric_name, team, a, b)` | the metric over two minute windows and the change |
| `get_sequence(event_id, before, after)` | the events around an event (max 20 each way) |
| `get_freeze_frame(event_id)` | positions and facing, plus pressure / risk / options |
| `get_player_context(player_id)` | a player's touches, passes, shots, xG, xT, bad situations |
| `list_moments(since_minute)` | moments from `core/moments` |

```sh
make mcp                                                       # stdio, demo match
uv run python -m agents.mcp_server --database [--match-id ID]  # interpreter's Postgres, READ ONLY session
```

Metric names and their meaning: `docs/metrics/REGISTRY.md`.

## Model adapter

`agents/llm/`: Gemini for development; Azure Foundry in production
(gpt-5-mini Analyst, gpt-4.1-mini Narrator/Localizer, southafricanorth). Every
paid call goes through `core/budget.py`.

## Narration pipeline (Phase 3b-1)

`agents/pipeline/`, on Microsoft Agent Framework (`agent-framework-core`):

```
Moment -> Analyst -> Narrator -> Verifier -+-> Localizer -> Overlay (pending) -> Producer
                        ^                  |
                        +---- Retry -------+  (max 2 retries, then a template sentence)
```

- **Numbers come from code.** `Analysis.values` = the Moment's before/after
  metrics; models only choose words. The fallback sentence uses those values only.
- **Verifier (code):** every number must match a value (with the line's
  rounding, or as a %) or the match context (score, minutes, shirts, players
  on the pitch); every capitalised name must be a team or a player on the
  pitch; predictions and blaming one event on the weather are rejected;
  injury/referee talk raises the risk tier (a human approves before it airs).
- **Producer (code):** stat cards and recaps air at once; a narrative must
  air within 8 s of its moment (viewer seconds: x replay speed in match time)
  or it expires; one narrative per 45 match seconds, most important first;
  goals and red cards preempt (air at once, push out lower lines).
- **Models:** each agent calls a model through `agents/llm` (budget kill
  switch). `LLM_PROVIDER=fake` is a free, deterministic model for tests, with
  error injection (`FakeProvider(errors=1, error="wrong_number")`).
- **Narrator voice:** `agents/narrator/examples.yaml` (Ian's lines).

## What the Verifier checks (Phases 3b-2, 3b-3)

Every line, in code, against code-made values, facts and counts
(`agents/pipeline/facts.py`):

- numbers (with the line's rounding, or as a %) and **who they belong to**
  (another team's control or xG is rejected);
- who is leading or trailing (the score decides);
- counts in words or digits before a football noun ("one pass", "ten men",
  "second counter goal", "twice") against passes in the move, players on the
  pitch, goals and counter goals;
- comparisons ("halved", "doubled", "up by a third") within 10% of a real
  before/after change;
- persona: no decimals in a casual line;
- a goal from a counter behind the full-back (the detector's own rule, run on
  the goal's move) must name the counter and the side;
- names: teams and players on the team sheet (`Match.lineups`); a position,
  style or shirt said with a name must match the sheet ("left-back
  Lindqvane", "number 5 Stonebridge"); "last man" only when the events show
  a last-man foul;
- predictions including soft
  ones ("seal it", "game over"), weather blame, copying a style example;
- injury/referee talk: allowed only after a human approves (risk tier high).

Translations (French, Spanish, Swahili, Arabic) see names, scores and numbers
as locked tokens and are checked again in code.

## Failure recovery, tracing, recaps, live (Phase 3c)

- **Recovery** (`pipeline/resilience.py`): a time budget per agent call; a
  timeout, 429 or 5xx gets one retry after a pause (on top of Gemini's own
  pacing and retries); a bad request is not retried. No answer -> code:
  Analyst -> code Insight, Narrator -> template line, Localizer -> that
  language dropped. An MCP tool error: one retry, then the Analyst goes on
  without it. The budget kill switch stops all model calls; templates only.
  Fake-model failure modes test each path (`tests/unit/test_resilience.py`).
- **Tracing** (`agents/telemetry.py`, OpenTelemetry): one trace per moment:
  `moment -> narrate -> analyst (mcp.get_sequence, llm.analyst) -> narrator
  -> verifier (passed, reasons) -> localizer.<lang> -> producer.offer`, and
  `producer.air` / `producer.expire` join it later. Spans carry latency,
  tokens and cost. `OTEL_EXPORTER=console|otlp|azure` (azure: Phase 7).
- **Recaps** (`pipeline/recap.py`): half-time and full-time, casual and
  analyst, from aired (verified) lines and the MatchState only; checked by
  the Verifier ("sealed the win" is allowed only at full time); template
  fallback; saved as overlays with evidence.
- **Live** (`agents/live/`): consumes `match-events`, runs the detector,
  stat cards at once, narrates moments with importance >= 0.7 (most
  important first; already-stale moments skipped before any model call),
  recaps at half-time and full-time, publishes every overlay status change
  to the `overlays` topic.
