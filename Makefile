.PHONY: help up down test lint infra

help:
	@echo "Targets:"
	@echo "  up     docker compose up -d (Kafka + Postgres)"
	@echo "  down   docker compose down"
	@echo "  test   uv run pytest -q tests/spec tests/unit"
	@echo "  lint   uv run ruff check . && ruff format --check ."
	@echo "  infra  Bicep deploy (stub)"

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
