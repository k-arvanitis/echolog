SHELL := /bin/bash

.PHONY: help infra-up infra-down infra-logs api worker ui stack test lint format eval-ami clean-eval

help:
	@echo "Targets:"
	@echo "  make infra-up     # start postgres, redis, qdrant"
	@echo "  make infra-down   # stop docker services"
	@echo "  make infra-logs   # tail docker service logs"
	@echo "  make api          # run FastAPI app"
	@echo "  make worker       # run Celery worker"
	@echo "  make stack        # start infra, worker, and api in tmux"
	@echo "  make test         # run pytest"
	@echo "  make lint         # run ruff"
	@echo "  make eval-ami     # run full AMI eval with English forced"
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

stack: infra-up
	@tmux has-session -t mie_stack 2>/dev/null && tmux kill-session -t mie_stack || true
	tmux new-session -d -s mie_stack 'cd /home/karvanitis/asr-project && uv run meeting-worker'
	tmux split-window -t mie_stack 'cd /home/karvanitis/asr-project && uv run meeting-api'
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

clean-eval:
	rm -rf data/eval/*
	rm -f eval/results/*
