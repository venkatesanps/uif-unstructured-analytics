PY      ?= python3
VENV    ?= .venv
BIN      = $(VENV)/bin
LLM     ?= rules
export UIF_HOME := $(CURDIR)
export PYTHONPATH := $(CURDIR)/src

.PHONY: setup synth run eval eval-replay test ci review clean up down

setup:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q -e ".[dev,synth]"
	@echo "Optional: brew install tesseract (scanned PDFs). Model-backed runs: LLM=handoff (Claude Code/Copilot) or LLM=anthropic (gateway); see README."

synth:
	$(BIN)/uif synth --out synthetic --n 12

run:
	$(BIN)/uif run synthetic/merchant --source merchant --system onboarding_portal --llm $(LLM)
	$(BIN)/uif run synthetic/dispute --source merchant --system disputes_portal --llm $(LLM)
	$(BIN)/uif run synthetic/internal --source internal --system case_mgmt --llm $(LLM)
	$(BIN)/uif run synthetic/external --source external --system web --llm $(LLM)

eval:
	$(BIN)/uif eval synthetic --llm $(LLM)

test:
	$(BIN)/pytest -q

ci: test eval eval-replay

review:
	$(BIN)/pip install -q streamlit && $(BIN)/streamlit run review_ui/app.py

up:
	docker compose up -d

down:
	docker compose down

clean:
	rm -rf .uif .pytest_cache

# Replay the saved agent answers for the golden set (no agent needed): proves the handoff path end to end.
eval-replay:
	mkdir -p .uif/replay/store/handoff/responses
	cp evals/handoff-golden/*.json .uif/replay/store/handoff/responses/
	UIF_STORE=.uif/replay/store UIF_DUCKDB=.uif/replay/uif.duckdb $(BIN)/uif eval synthetic --llm handoff
