# UIF — Unstructured-data Intelligence Framework (Phase 0)

Turns merchant-services documents (statements, analyst notes, emails, scans) into typed,
evidence-linked facts and analytics marts. Same code runs on a laptop (synthetic data, DuckDB,
rules or Ollama) and in AWS (S3, Textract, Comprehend, Bedrock, Step Functions, Snowflake).

```
landing → intake → normalize → guard → classify → extract → resolve → validate → publish → marts
                    (OCR/email)  (PAN/PII    (keywords,   (schema +   (MID,      (grounding,  (DuckDB |
                                  tokens)     LLM if      evidence)   fuzzy      rules,       Snowpipe)
                                              unsure)                 name)      review)
```

## Quick start (laptop)

```bash
make setup             # venv + deps   (optional: brew install tesseract  -> scanned PDFs)
make synth             # 13 labeled synthetic docs + data/merchant_master.csv
make run               # process them with the offline rules baseline
make -s eval           # golden metrics + gates, JSON to stdout
make test              # 28 tests: unit, contract, golden, adversarial, integration, aws (moto)
.venv/bin/uif sql "select * from mart_underwriting_variance"
.venv/bin/uif review   # open review queue      (make review -> Streamlit reviewer UI)
```

With your local model:

```bash
ollama pull hermes3:latest
LLM=ollama make run && LLM=ollama make -s eval
pytest -m ollama -s    # checks the model recovers the layout the rules baseline can't read
```

## What the golden run shows (rules baseline, 2026-10-13)

| Metric | Value | Gate |
| --- | --- | --- |
| Classification accuracy | 1.00 | ≥ 0.95 |
| Required-field F1 | 0.957 | ≥ 0.90 |
| All-field F1 | 0.949 | reported |
| Grounding rate | 1.00 | ≥ 0.99 |
| PII/PAN leakage | 0 | = 0 |
| Entity accuracy | 1.00 | reported |
| Adversarial (injection) doc | pass | must pass |

Read these honestly: the rules baseline's hints were written for synthetic layouts A and B, so
those score perfectly. The point is the plumbing and the safety behaviour: layout C (unseen)
extracts nothing and lands in review with `missing_required` instead of guessing; the flyer is parked
as `unknown_doc_type`; the merchant missing from master data is flagged; planted card numbers and
SSNs never leave `raw/`/`restricted/`. Real accuracy is measured with `LLM=ollama` locally and
Bedrock in AWS, against redacted real samples (Phase 1–2).

## Safety model, in code

- `raw/` and `restricted/` are the only places un-tokenized text exists (`context.KEYS`).
- `steps/guard.py` fails closed: a document it cannot scan is quarantined, never classified.
- PAN detection = Luhn + card-brand prefix + "not right after MID/TID/invoice" (`providers/local.py`).
- Extractors must return value + page + quote + confidence (`llm_common.response_schema`);
  Bedrock is called with a forced tool call, Ollama with a JSON-schema `format`.
- `steps/validate.py` sends a fact to review when its quote is not on the page, the number is not in
  its own quote, a cross-field rule fails, confidence is low, or the enum is out of range.
  `tests/adversarial` proves a model that obeys injected text gets caught either way.

## Layout

```
config/            local.yaml, aws.yaml (env-expanded)
registry/          doc_types/<type>/schema.json + prompt.md   <- add document types here
src/uif/           contracts, providers/{local,aws}, steps/, runner, aws_handler, evals, synth, review
orchestrator/      statemachine.asl.json (same step order as runner.py; a test enforces it)
sql/               duckdb/core.sql (local CORE + marts), snowflake/core.sql (stage, pipe, MERGE, masking)
review_ui/         Streamlit reviewer
tests/             unit, contract, golden, adversarial, integration, aws (moto), ollama (live)
.claude/           skills: new-doc-type, run-golden-eval, extraction-debugger, snowflake-ddl,
                   aws-deploy-check; agents: schema-reviewer, pii-auditor, prompt-tuner
Dockerfile         --target lambda (light steps) / --target task (ECS: normalize, extract)
infra/README.md    resources and IAM boundaries for Phase 2
```

## Not in Phase 0 (by design)

- Not exercised against real AWS: Textract, Comprehend and Bedrock adapters are written; Bedrock is
  contract-tested with a stub client, S3/handler flow with moto. First real run is the dev-account smoke test.
- Snowflake DDL is written but not executed; IaC is listed in `infra/README.md`, not built.
- Audio (whisper.cpp / Transcribe), embeddings and vector search, Signal Builder, Schema Designer and
  the Q&A agent arrive in Phases 1–3.
