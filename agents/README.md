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
