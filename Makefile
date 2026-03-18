.PHONY: up down shell migrate migrate-down migrate-create test lint format type-check

# Pick an available Python command across Windows/MSYS2/Linux.
# Preference: python3 -> python -> py (Windows launcher)
PY := $(shell sh -c 'if command -v python3 >/dev/null 2>&1; then echo python3; elif command -v python >/dev/null 2>&1; then echo python; elif command -v py >/dev/null 2>&1; then echo py; else echo python; fi')

up:
	docker compose up -d --build

down:
	docker compose down -v

shell:
	docker compose exec app bash

migrate:
	docker compose run --rm app python -m alembic upgrade head

migrate-down:
	docker compose run --rm app python -m alembic downgrade -1

migrate-create:
	docker compose run --rm app python -m alembic revision --autogenerate -m "$(msg)"

test:
	pytest

lint:
	$(PY) -m ruff check .

format:
	$(PY) -m ruff format .

type-check:
	$(PY) -m mypy .

