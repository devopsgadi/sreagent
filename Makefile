.PHONY: up down dev install test smoke logs

up:            ## Build and run everything in Docker (UI on :3000)
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f agent-api

install:       ## Local dev install (Python venv + UI deps)
	python3 -m venv .venv
	.venv/bin/pip install -r mcp_servers/requirements.txt -r agent_api/requirements.txt pytest pytest-asyncio
	cd ui && npm install

dev:           ## Run all services locally without Docker (Ctrl+C stops all)
	./scripts/dev.sh

test:
	.venv/bin/python -m pytest -q agent_api/tests

smoke:         ## End-to-end check against a running stack
	./scripts/smoke.sh
