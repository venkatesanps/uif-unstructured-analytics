PY      ?= python3
VENV    ?= .venv
BIN      = $(VENV)/bin
LLM     ?= rules
export UIF_HOME := $(CURDIR)
export PYTHONPATH := $(CURDIR)/src

.PHONY: setup synth run eval test ci review clean up down

setup:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q -e ".[dev,synth]"
	@echo "Optional: brew install tesseract (scanned PDFs) ; ollama pull hermes3:latest (local LLM)"

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

ci: test eval

review:
	$(BIN)/pip install -q streamlit && $(BIN)/streamlit run review_ui/app.py

up:
	docker compose up -d

down:
	docker compose down

clean:
	rm -rf .uif .pytest_cache
