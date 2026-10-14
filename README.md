# UIF — Unstructured-data Intelligence Framework (Phase 0 + dispute rebuttals)

Turns merchant-services documents (statements, analyst notes, chargeback rebuttal packets,
emails with attachments, scans) into typed,
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
make synth             # 19 labeled synthetic docs + data/merchant_master.csv + outcomes
make run               # process them with the offline rules baseline
make -s eval           # golden metrics + gates, JSON to stdout
make test              # 49 tests: unit, contract, golden, adversarial, integration, aws (moto)
.venv/bin/uif sql "select * from mart_underwriting_variance"
.venv/bin/uif sql "select * from mart_evidence_gaps"
.venv/bin/uif review   # open review queue      (make review -> Streamlit reviewer UI)
```

## Using Claude at work (no Ollama needed)

Pick whichever your firm allows; all three feed the same validator, gates and marts.

| Mode | `--llm` | Needs | How it runs |
| --- | --- | --- | --- |
| Agent handoff | `handoff` | Claude Code or Copilot agent mode | Pipeline writes tokenized requests; the agent answers them per `AGENT_EXTRACT.md`; rerun picks them up |
| Claude API / gateway | `anthropic` | An endpoint that speaks the Messages API + a key or bearer token | Direct calls; set `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`, `ANTHROPIC_AUTH=bearer` for gateways |
| Bedrock | `bedrock` | AWS account with Claude enabled | Used by the AWS runtime (`config/aws.yaml`) |

Agent handoff, step by step:

```bash
LLM=handoff make run                      # documents park at extract: "waiting for an agent"
# Claude Code:  "/agent-extract"  (skill in .claude/skills)   Copilot: run the agent-extract prompt
.venv/bin/uif handoff check               # responses well-formed?
.venv/bin/uif run synthetic/merchant --source merchant --llm handoff --force   # resume (each folder)
.venv/bin/uif eval synthetic --llm handoff --no-run
```

The agent sees only guard-tokenized text, the same text a hosted model would see. Before putting
**real** documents through any agent or gateway, confirm your firm's data-handling approval for that
tool and data class. The design assumes synthetic or redacted data on laptops.

Both Claude adapters use `tool_choice: auto` plus a JSON-text fallback. The newest Claude models
return 400 on a forced tool choice. Strict tool mode isn't used either: it caps nullable unions
at 16 per request, and these schemas need more.

## What the golden run shows (2026-10-13, 19 docs)

| Metric | Rules baseline | Claude via handoff | Gate |
| --- | --- | --- | --- |
| Classification accuracy | 1.00 | 1.00 | ≥ 0.95 |
| Required-field F1 | 0.950 | 1.00 | ≥ 0.90 |
| All-field F1 | 0.948 | 1.00 | reported |
| Grounding rate | 1.00 | 1.00 | ≥ 0.99 |
| PII/PAN leakage | 0 | 0 | = 0 |
| Entity accuracy | 0.947 | 1.00 | reported |
| Facts sent to review | 0% | 0.6% (one sale date with no year printed) | reported |
| Adversarial (injection) docs | pass | pass | must pass |

Saved in `evals/baseline-*.json`; `make eval-replay` replays the saved agent answers
(`evals/handoff-golden/`) so CI checks the handoff path without an agent.

The handoff column is a format and plumbing baseline, **not an independent accuracy number**: the
answers were written by Claude in the same session that wrote the synthetic generator, and the
documents are clean. Claude recovered the two layouts the rules baseline can't read: the unseen
statement and the freeform rebuttal email. The real number comes from your agent at work on
redacted real samples.

## Local agent vs Bedrock (parity)

Locally you extract with Claude Code or Copilot; production uses Bedrock. `PARITY.md` is the runbook.
Bedrock answers the exact requests your agent answered (same tokenized text, prompts and schema), and
`uif parity diff --labels synthetic` reports field-by-field agreement plus each side's score against
the golden labels. That report is the Gate C evidence that laptop results predict production.

The tooling was checked end to end here with the rules baseline standing in for Bedrock (answer,
export, unpack, diff, score). It correctly failed parity (90.5% required-field agreement) on the
two layouts rules can't read.

Read these honestly: the rules baseline's hints were written for the synthetic layouts, so
those score perfectly. The point is the plumbing and the safety behaviour: the unseen statement
layout and the freeform rebuttal email extract nothing usable and lands in review with `missing_required` instead of guessing; the flyer is parked
as `unknown_doc_type`; the merchant missing from master data is flagged; planted card numbers and
SSNs never leave `raw/`/`restricted/`. Real accuracy is measured with `LLM=ollama` locally and
Bedrock in AWS, against redacted real samples (Phase 1–2).

## Dispute rebuttal packets

`registry/doc_types/dispute_rebuttal/` reads a merchant's chargeback response, whether it arrives as one
PDF or as an email with attachments (each attachment becomes labelled pages; image attachments and
image-only pages go through OCR). It extracts case number, network, reason code, amount, sale date,
order number, the evidence actually included, and the merchant's argument.

Reference data drives two schema rules: the reason code must exist (`in_ref`) and must belong to the
stated network (`ref_pair`), using `data/reference/reason_codes.csv`. Its `required_evidence` column is
an **illustrative placeholder**, not network compelling-evidence rules; swap in your disputes team's
version before using the marts for decisions.

| Mart | Answers |
| --- | --- |
| `mart_dispute_packet` | One typed row per packet |
| `mart_dispute_evidence` | Required vs present vs missing evidence per packet, completeness, outcome |
| `mart_dispute_win_rate` | Win rate by reason category, complete vs incomplete packets |
| `mart_evidence_gaps` | Which evidence merchants most often fail to send, and the dollars at stake |

Outcomes come from `data/reference/dispute_outcomes.csv`, a synthetic stand-in for the dispute system;
in Snowflake the view joins the real case table. With six synthetic packets the win rates are
plumbing, not findings.

## Safety model, in code

- `raw/` and `restricted/` are the only places un-tokenized text exists (`context.KEYS`).
- `steps/guard.py` fails closed: a document it cannot scan is quarantined, never classified.
- PAN detection = Luhn + card-brand prefix + "not right after MID/TID/invoice" (`providers/local.py`).
- Extractors must return value + page + quote + confidence (`llm_common.response_schema`);
  Bedrock is called with a forced tool call, Ollama with a JSON-schema `format`.
- `steps/validate.py` sends a fact to review when its quote is not on the page, the number is not in
  its own quote, a cross-field rule fails, confidence is low, or the enum is out of range.
  List fields need every item supported somewhere in the document, so one quote can't vouch for
  a whole evidence list. `tests/adversarial` proves a model that obeys injected text is caught.

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
