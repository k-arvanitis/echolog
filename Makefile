SHELL := /bin/bash

.PHONY: help demo infra-up infra-down infra-logs api worker ui stack test lint format docker-build eval-ami eval-rag clean-eval

help:
	@echo "Targets:"
	@echo "  make demo          # one command: infra + embedding model + worker/api/frontend"
	@echo "  make infra-up      # start postgres, redis, qdrant"
	@echo "  make infra-down    # stop docker services"
	@echo "  make infra-logs    # tail docker service logs"
	@echo "  make api           # run FastAPI app on :8001"
	@echo "  make worker        # run Celery worker"
	@echo "  make ui            # run Next.js dev server on :3000"
	@echo "  make stack         # start infra, worker, and api in tmux"
	@echo "  make test          # run pytest"
	@echo "  make lint          # run ruff check + ruff format --check"
	@echo "  make format        # apply ruff format"
	@echo "  make docker-build  # build the API/worker runtime image"
	@echo "  make eval-ami      # run full AMI WER eval (English forced)"
	@echo "  make eval-rag      # run RAG QA eval over fixed question set"
	@echo "  make clean-eval    # remove eval scratch (keeps published results)"

demo: infra-up
	ollama pull nomic-embed-text
	@if command -v tmux >/dev/null 2>&1; then \
		tmux has-session -t echolog 2>/dev/null && tmux kill-session -t echolog || true; \
		tmux new-session -d -s echolog 'cd $(CURDIR) && uv run meeting-worker'; \
		tmux split-window -t echolog 'cd $(CURDIR) && uv run meeting-api'; \
		tmux split-window -t echolog 'cd $(CURDIR)/frontend && npm run dev'; \
		tmux select-layout -t echolog tiled; \
		echo "tmux session started: echolog (attach with: tmux attach -t echolog)"; \
	else \
		echo "tmux not found — run each service in its own terminal:"; \
		echo "  uv run meeting-worker"; \
		echo "  uv run meeting-api"; \
		echo "  (cd frontend && npm run dev)"; \
	fi
	@echo "Open http://localhost:3000"

infra-up:
	docker compose up -d postgres redis qdrant

infra-down:
	docker compose down

infra-logs:
	docker compose logs -f postgres redis qdrant

api:
	uv run meeting-api

worker:
	uv run meeting-worker

ui:
	cd frontend && npm run dev

stack: infra-up
	@tmux has-session -t echolog 2>/dev/null && tmux kill-session -t echolog || true
	tmux new-session -d -s echolog 'cd $(CURDIR) && uv run meeting-worker'
	tmux split-window -t echolog 'cd $(CURDIR) && uv run meeting-api'
	tmux split-window -t echolog 'cd $(CURDIR)/frontend && npm run dev'
	tmux select-layout -t echolog tiled
	@echo "tmux session started: echolog"
	@echo "attach with: tmux attach -t echolog"

test:
	uv run --extra dev pytest

lint:
	uv run --extra dev ruff check .
	uv run --extra dev ruff format --check .

format:
	uv run --extra dev ruff format .

docker-build:
	docker build -t meeting-intelligence-engine:latest .

eval-ami:
	MIE_LANGUAGE=en uv run mie-eval-ami \
		--csv eval/results/ami_eval_all_meetings_en.csv \
		--json eval/results/ami_eval_all_meetings_en.json

eval-rag:
	uv run --extra eval mie-eval-rag \
		--qa-dir eval/rag_qa \
		--json eval/results/rag_eval_results.json

clean-eval:
	rm -rf data/eval/*
	find eval/results -type f ! -name 'ami_eval_all_meetings_en.json' ! -name 'rag_eval_results.json' -delete
