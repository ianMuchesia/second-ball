.PHONY: help up down test lint infra contracts contracts-check shapes demo realism realism-reference replay

help:
	@echo "Targets:"
	@echo "  up     docker compose up -d (Kafka + Postgres)"
	@echo "  down   docker compose down"
	@echo "  test   uv run pytest -q tests/spec tests/unit"
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

up:
	docker compose up -d

down:
	docker compose down

test:
	uv run pytest -q tests/spec tests/unit

lint:
	uv run ruff check .
	uv run ruff format --check .

infra:
	@echo "infra: stub, nothing deployed yet (see infra/main.bicep)"

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
MATCH_FILE = $(if $(filter demo,$(MATCH)),demo/match.jsonl,$(MATCH))
TIMELINE = docs/timelines/$(basename $(notdir $(if $(filter demo,$(MATCH)),demo,$(MATCH)))).csv

replay:
	@test "$(MATCH)" != demo || test -f demo/match.jsonl || $(MAKE) demo
	uv run python -m stream.interpreter --exit-on-end --timeline $(TIMELINE) & pid=$$!; \
		uv run python -m stream.replayer $(MATCH_FILE) --speed $(SPEED) \
			--wait-for-group interpreter && wait $$pid
	uv run python -m scripts.timeline $(TIMELINE)
