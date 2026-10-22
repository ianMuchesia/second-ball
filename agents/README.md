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
- **Producer (code):** stat cards air at once; a narrative must air within
  8 s of its moment (viewer seconds: x replay speed in match time) or it
  expires; one narrative per 45 s, most important first.
- **Models:** each agent calls a model through `agents/llm` (budget kill
  switch). `LLM_PROVIDER=fake` is a free, deterministic model for tests, with
  error injection (`FakeProvider(errors=1, error="wrong_number")`).
- **Narrator voice:** `agents/narrator/examples.yaml` (Ian's lines).
