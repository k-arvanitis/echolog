SHELL := /bin/bash

.PHONY: help infra-up infra-down infra-logs api worker frontend stack test lint format eval-ami eval-rag clean-eval

help:
	@echo "Targets:"
	@echo "  make infra-up     # start postgres, redis, qdrant"
	@echo "  make infra-down   # stop docker services"
	@echo "  make infra-logs   # tail docker service logs"
	@echo "  make api          # run FastAPI app on :8001"
	@echo "  make worker       # run Celery worker"
	@echo "  make frontend     # run Next.js dev server on :3000"
	@echo "  make stack        # start infra, worker, and api in tmux"
	@echo "  make test         # run pytest"
	@echo "  make lint         # run ruff"
	@echo "  make eval-ami     # run full AMI WER eval (English forced)"
	@echo "  make eval-rag     # run RAG QA eval over fixed question set"
	@echo "  make clean-eval   # remove eval scratch/results"

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

frontend:
	cd frontend && npm run dev

stack: infra-up
	@tmux has-session -t mie_stack 2>/dev/null && tmux kill-session -t mie_stack || true
	tmux new-session -d -s mie_stack 'cd $(CURDIR) && uv run meeting-worker'
	tmux split-window -t mie_stack 'cd $(CURDIR) && uv run meeting-api'
	tmux split-window -t mie_stack 'cd $(CURDIR)/frontend && npm run dev'
	tmux select-layout -t mie_stack tiled
	@echo "tmux session started: mie_stack"
	@echo "attach with: tmux attach -t mie_stack"

test:
	uv run --extra dev pytest

lint:
	uv run --extra dev ruff check .

format:
	uv run --extra dev ruff format .

eval-ami:
	MIE_LANGUAGE=en uv run mie-eval-ami \
		--csv eval/results/ami_eval_all_meetings_en.csv \
		--json eval/results/ami_eval_all_meetings_en.json

eval-rag:
	uv run --extra eval mie-eval-rag \
		--qa-file eval/rag_qa/all_meetings_qa.json \
		--output eval/results/rag_eval_results.json

clean-eval:
	rm -rf data/eval/*
	rm -f eval/results/*
