# 04 Runbooks

## A. First run on a laptop

```bash
git clone https://github.com/venkatesanps/uif-unstructured-analytics.git
cd uif-unstructured-analytics
make setup            # venv + deps (Python 3.10+)
make test             # 86 tests; Ollama test skips
make run              # golden set with the offline rules baseline
.venv/bin/uif sql "select * from mart_underwriting_variance"
.venv/bin/uif review  # open review queue   (make review -> Streamlit UI)
```

Optional system tools: `tesseract` (scans, photos, faxes), `ffmpeg` (audio), `espeak-ng` or macOS
`say` (generating audio samples), `whisper-cpp` + a ggml model (real speech recognition).

## B. Extract with Claude Code or Copilot at work (handoff)

```bash
LLM=handoff make run                     # documents park at extract: "waiting for an agent"
# Claude Code:  /agent-extract           Copilot: run .github/prompts/agent-extract.prompt.md
.venv/bin/uif handoff check              # must say "responses look well-formed"
.venv/bin/uif run synthetic/merchant --source merchant --llm handoff --force   # resume (each folder)
.venv/bin/uif eval synthetic --llm handoff --no-run
```

The agent reads only `handoff/requests/*.json` (guard-tokenized text) and writes
`handoff/responses/<id>.json`. Rules are in `AGENT_EXTRACT.md`. Copilot may run a different model
family: keep its answers as a separate set (`evals/golden/answers/copilot`).

## C. Claude through an API gateway

```bash
export ANTHROPIC_BASE_URL=https://<gateway>/anthropic   ANTHROPIC_AUTH=bearer
export ANTHROPIC_KEY_ENV=GATEWAY_TOKEN   GATEWAY_TOKEN=...   ANTHROPIC_MODEL=<model name>
LLM=anthropic make run
```

## D. Bedrock parity (Gate C evidence)

Full steps in `PARITY.md`. Short version:

1. Laptop: `uif handoff export requests --out golden-requests.zip`
2. `aws s3 cp golden-requests.zip s3://$UIF_BUCKET/uif/handoff/inbox/`
3. ECS one-off task: `python -m uif.cli --runtime aws handoff answer --with bedrock
   --bundle store:handoff/inbox/golden-requests.zip --out store:handoff/outbox/bedrock-answers.zip`
4. Download, then `uif handoff import --path bedrock-answers.zip --to evals/golden/answers/bedrock`
5. `make parity` → `evals/parity-report.md`

Needs: Bedrock model access, `UIF_BEDROCK_MODEL_ID`, task role with `bedrock:InvokeModel` and S3 on
`handoff/*`.

## E. Add a document type

Use the Claude Code skill `new-doc-type`. It writes the schema and prompt, adds a synthetic
generator with a layout the hints don't cover, adds golden tests, and runs `schema-reviewer`.
Done when `make ci` is green and the unseen layout lands in review.

## F. After any change to the guard

```bash
.venv/bin/uif reguard        # re-guards every stored doc, purges handoff requests it would now change
# then rerun the pipeline with --force
```

Stored outputs keep whatever the old guard missed until you do this.

## G. When a golden replay test fails ("drifted")

Request IDs come from the tokenized text. A change to the generator, guard, a schema or a prompt
changes them. Regenerate requests with `LLM=handoff make run` on a fresh store, re-answer only the
changed ones, and replace those pairs in `evals/<set>/requests` and `answers`. Never hand-edit an
answer to make a test pass.

## H. Audio

```bash
make audio                                  # regenerate recordings (espeak-ng or macOS say + ffmpeg)
UIF_TRANSCRIBER=reference:samples/audio/labels .venv/bin/uif eval samples/audio   # extraction only
UIF_TRANSCRIBER=whisper UIF_WHISPER_MODEL=~/models/ggml-base.en.bin .venv/bin/uif eval samples/audio
UIF_TRANSCRIBER=pocketsphinx .venv/bin/uif eval samples/audio   # low-accuracy fallback (all reviewed)
```

## I. Debug a wrong fact

Claude Code skill `extraction-debugger`: given a doc_id or file name, it replays the steps, shows
classification, extractor output, quote and the validator's reason, then walks a decision tree to
the fix.

## J. Delivering code to the work network

Email attachments of code are blocked by the firm's attachment policy. Use the GitHub repo
(`git clone` or **Code → Download ZIP**), if bringing external code in is permitted. Check the
policy for that too.
