.PHONY: help up down test test-slow lint infra contracts contracts-check shapes demo realism realism-reference replay eval-moments mcp narrate live jaeger eval-narration eval-latency record api e2e

help:
	@echo "Targets:"
	@echo "  up     docker compose up -d (Kafka + Postgres)"
	@echo "  down   docker compose down"
	@echo "  test   uv run pytest -q tests/spec tests/unit (not the slow full seasons)"
	@echo "  test-slow  the full-season statistics (hundreds of matches; nightly in CI)"
	@echo "  lint   uv run ruff check . && ruff format --check ."
	@echo "  infra  Bicep deploy (stub)"
	@echo "  contracts        regenerate docs/schemas and web/src/types from core/contracts"
	@echo "  contracts-check  fail if the generated files are out of date"
	@echo "  shapes  draw Riverside's shapes into docs/shapes/"
	@echo "  demo    demo SCENARIO: Riverside v Harbour Town (scripted) -> demo/"
	@echo "  realism            500 matches vs real bands -> docs/DATA_REALISM.md"
	@echo "  realism-reference  re-download the real reference bands"
	@echo "  replay  MATCH=demo|<file.jsonl> SPEED=1|10|60: replay into Kafka, interpret,"
	@echo "          timeline CSV + PNG -> docs/timelines/ (needs make up)"
	@echo "  eval-moments  moment detector vs the demo's answer key + 50 free matches -> docs/EVAL.md"
	@echo "  mcp     football MCP server (stdio) over demo/match.jsonl"
	@echo "  narrate  demo big moments through the pipeline (PROVIDER=gemini for a real model)"
	@echo "  live    live narrator + replay: MATCH=demo SPEED=10 -> overlays topic + docs/overlays/"
	@echo "  jaeger  start Jaeger for traces (then OTEL_EXPORTER=otlp), UI :16686"
	@echo "  eval-narration  repeat runs: first-pass/retry/fallback rates -> docs/EVAL.md"
	@echo "  eval-latency    live demo at SPEED, p50/p95 per stage -> docs/EVAL.md"
	@echo "  record  MATCH=demo: the full pipeline once -> runs/demo-fake/ (PROVIDER=gemini: runs/demo/, asks first)"
	@echo "  api     broadcast API + built screen on :8000 (cd web && npm run build first)"
	@echo "  e2e     Playwright smoke test (fake-model bundle, no network)"

up:
	docker compose up -d

down:
	docker compose down

test:
	uv run pytest -q -m "not slow" tests/spec tests/unit

test-slow:  # the full-season statistics (hundreds of matches): nightly in CI
	uv run pytest -q -m slow tests/unit

lint:
	uv run ruff check .
	uv run ruff format --check .

infra:  # compiles infra/main.bicep; deploying: infra/README.md
	az bicep build --file infra/main.bicep --stdout > /dev/null && echo "infra/main.bicep: OK"

contracts:
	uv run python -m scripts.export_contracts

contracts-check: contracts
	@git diff --exit-code -- docs/schemas web/src/types && \
		test -z "$$(git ls-files --others --exclude-standard -- docs/schemas web/src/types)" || \
		{ echo "Contracts drifted: run 'make contracts' and commit."; exit 1; }

shapes:
	uv run python -m scripts.render_shapes riverside_athletic

demo:
	uv run python -m engine.generate --demo --out demo

realism:
	uv run python -m evals.realism.report

realism-reference:
	uv run python -m evals.realism.fetch_reference --refresh

MATCH ?= demo
SPEED ?= 10
# The model: the free fake one unless asked (PROVIDER=gemini); real ones ask first.
PROVIDER ?= fake
MATCH_FILE = $(if $(filter demo,$(MATCH)),demo/match.jsonl,$(MATCH))
TIMELINE = docs/timelines/$(basename $(notdir $(if $(filter demo,$(MATCH)),demo,$(MATCH)))).csv

replay:
	@test "$(MATCH)" != demo || test -f demo/match.jsonl || $(MAKE) demo
	uv run python -m stream.interpreter --exit-on-end --timeline $(TIMELINE) & pid=$$!; \
		uv run python -m stream.replayer $(MATCH_FILE) --speed $(SPEED) \
			--wait-for-group interpreter && wait $$pid
	uv run python -m scripts.timeline $(TIMELINE)

eval-moments:
	uv run python -m evals.moments.report

mcp:
	@test -f demo/match.jsonl || $(MAKE) demo
	uv run python -m agents.mcp_server --match-file demo/match.jsonl

narrate:
	@test -f demo/match.jsonl || $(MAKE) demo
	uv run python -m scripts.narrate_demo --provider $(PROVIDER)

live:
	@test "$(MATCH)" != demo || test -f demo/match.jsonl || $(MAKE) demo
	uv run python -m agents.live --speed $(SPEED) --exit-on-end --provider $(PROVIDER) \
		--out docs/overlays/$(basename $(notdir $(MATCH_FILE))).jsonl & pid=$$!; \
		uv run python -m stream.replayer $(MATCH_FILE) --speed $(SPEED) \
			--wait-for-group narrator && wait $$pid

jaeger:
	docker compose --profile tracing up -d jaeger

eval-narration:
	uv run python -m evals.narration.report --runs 10 --translation-runs 2 --provider $(PROVIDER)

eval-latency:
	@test -f demo/match.jsonl || $(MAKE) demo
	uv run python -m evals.latency.report --speed $(SPEED) --provider $(PROVIDER)

RUN ?= $(basename $(notdir $(MATCH_FILE)))

record:
	@test "$(MATCH)" != demo || test -f demo/match.jsonl || $(MAKE) demo
	uv run python -m agents.live.record --provider $(PROVIDER) --match-file $(MATCH_FILE) --out runs/$(if $(filter demo,$(MATCH)),$(if $(filter fake,$(PROVIDER)),demo-fake,demo),$(RUN))

api:
	uv run uvicorn stream.api:app --port 8000

e2e:
	cd web && npm run e2e
