# Ego Labs developer commands. Run `make help` for the list.

BACKEND_PY ?= .venv/bin/python

.PHONY: help up down logs ps smoke seed setup test test-backend test-web lint gen-api migration

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

up: ## Build and start the full stack, waiting until every service is healthy
	docker compose up -d --build --wait

down: ## Stop the stack (keeps data volumes)
	docker compose down

logs: ## Follow logs from every service
	docker compose logs -f

ps: ## Show service status
	docker compose ps

smoke: ## End-to-end check against the running stack
	scripts/smoke.sh

seed: ## Sample data by real processing: upload sample clips, track hands and objects, classify movements (SEED_EMAIL of an admin, annotator, or reviewer)
	@test -n "$(SEED_EMAIL)" || (echo 'usage: make seed SEED_EMAIL=you@gmail.com (an account that has signed in with Google once: admin, annotator, or reviewer)' && exit 1)
ifeq ($(SEED_PASSWORD),)
	cd backend && $(BACKEND_PY) -m egolabs.seed --api $${API_URL:-http://localhost:8000} --token "$$($(BACKEND_PY) -m egolabs.token "$(SEED_EMAIL)")"
else
	cd backend && $(BACKEND_PY) -m egolabs.seed --api $${API_URL:-http://localhost:8000} --email "$(SEED_EMAIL)" --password "$(SEED_PASSWORD)"
endif

setup: ## Install backend (venv) and web dependencies for local development
	cd backend && python3 -m venv .venv && $(BACKEND_PY) -m pip install -q -e ".[dev]"
	cd web && npm install

test: test-backend test-web ## Run all tests

test-backend: ## Backend tests (needs PostgreSQL + Redis, e.g. `docker compose up -d postgres redis`)
	cd backend && $(BACKEND_PY) -m pytest

test-web: ## Web unit tests
	cd web && npm test

lint: ## Lint and type-check everything
	cd backend && $(BACKEND_PY) -m ruff check . && $(BACKEND_PY) -m ruff format --check .
	cd web && npm run lint && npm run typecheck

gen-api: ## Regenerate the web app's API types from the FastAPI schemas
	cd backend && $(BACKEND_PY) -m egolabs.openapi > ../web/lib/api/openapi.json
	cd web && npm run gen:api

migration: ## Create an Alembic migration from model changes: make migration m="add videos.rotation"
	@test -n "$(m)" || (echo 'usage: make migration m="describe the change"' && exit 1)
	cd backend && .venv/bin/alembic revision --autogenerate -m "$(m)"
