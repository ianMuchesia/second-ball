.PHONY: help up down test lint infra contracts contracts-check shapes demo

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
