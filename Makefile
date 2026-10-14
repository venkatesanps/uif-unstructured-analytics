PY      ?= python3
VENV    ?= .venv
BIN      = $(VENV)/bin
LLM     ?= rules
export UIF_HOME := $(CURDIR)
export PYTHONPATH := $(CURDIR)/src

.PHONY: setup synth samples audio run eval eval-replay eval-samples eval-audio parity test ci review clean up down

setup:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q -e ".[dev,synth]"
	@echo "Optional: brew install tesseract (scanned PDFs). Model-backed runs: LLM=handoff (Claude Code/Copilot) or LLM=anthropic (gateway); see README."

synth:
	$(BIN)/uif synth --out synthetic --n 12

# one labeled sample per file format (photo, fax TIFF, XLSX, CSV, ZIP, forwarded EML, JSON, DOCX, HTML, chat, Markdown)
samples:
	$(BIN)/uif synth --formats --out samples/formats

# speech recordings (needs espeak-ng or macOS `say`, plus ffmpeg)
audio:
	$(BIN)/uif synth --audio --out samples/audio

run:
	$(BIN)/uif run synthetic/merchant --source merchant --system onboarding_portal --llm $(LLM)
	$(BIN)/uif run synthetic/dispute --source merchant --system disputes_portal --llm $(LLM)
	$(BIN)/uif run synthetic/internal --source internal --system case_mgmt --llm $(LLM)
	$(BIN)/uif run synthetic/external --source external --system web --llm $(LLM)

eval:
	$(BIN)/uif eval synthetic --llm $(LLM)

test:
	$(BIN)/pytest -q

ci: test eval eval-replay eval-samples eval-audio

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
	cp evals/golden/answers/claude-code/*.json .uif/replay/store/handoff/responses/
	UIF_STORE=.uif/replay/store UIF_DUCKDB=.uif/replay/uif.duckdb $(BIN)/uif eval synthetic --llm handoff

# Agent vs Bedrock on the same golden requests (answers/bedrock comes back from AWS dev; see PARITY.md).
parity:
	$(BIN)/uif parity diff --labels synthetic --names claude-code,bedrock --report evals/parity-report.md --json evals/parity-report.json

# Score the format samples: rules baseline, then the saved Claude answers replayed (no agent needed).
eval-samples:
	UIF_STORE=.uif/samples/store UIF_DUCKDB=.uif/samples/uif.duckdb $(BIN)/uif eval samples/formats --llm rules > .uif/samples-rules.json
	rm -rf .uif/samples-replay && mkdir -p .uif/samples-replay/store/handoff/responses
	cp evals/formats/answers/claude-code/*.json .uif/samples-replay/store/handoff/responses/
	UIF_STORE=.uif/samples-replay/store UIF_DUCKDB=.uif/samples-replay/uif.duckdb $(BIN)/uif eval samples/formats --llm handoff > .uif/samples-claude.json
	@echo "sample evals passed gates: .uif/samples-rules.json, .uif/samples-claude.json"

# Audio: reference transcripts (stand-in for a good recognizer) with the saved Claude answers.
# Real recognition: UIF_TRANSCRIBER=whisper (whisper.cpp + UIF_WHISPER_MODEL) or pocketsphinx.
eval-audio:
	rm -rf .uif/audio-replay && mkdir -p .uif/audio-replay/store/handoff/responses
	cp evals/audio/answers/claude-code/*.json .uif/audio-replay/store/handoff/responses/
	UIF_TRANSCRIBER=reference:samples/audio/labels UIF_STORE=.uif/audio-replay/store UIF_DUCKDB=.uif/audio-replay/uif.duckdb \
	  $(BIN)/uif eval samples/audio --llm handoff > .uif/audio-claude.json
	@echo "audio eval passed gates: .uif/audio-claude.json"
