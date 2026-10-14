# 01 Design

## Goal

Turn any merchant-services document into typed, evidence-linked facts in Snowflake, keyed to the
merchant, so they can be used for analytics. Documents include PDFs, scans, photos, faxes, emails
with attachments, office files, chat exports, web pages and call recordings. Sources are
merchants, external parties, and internal teams (risk analysts and other departments). The same
code runs on a laptop against synthetic data and in AWS against real data; only the provider
config changes.

## Principles

1. **Schema-first.** Every document type has a versioned schema in `registry/doc_types/<type>/`.
   The model fills it; it never invents structure at run time.
2. **Evidence or it didn't happen.** Every value carries page, a verbatim quote and a confidence.
   The validator re-checks that the quote is on the page and that the value is in the quote.
3. **Guard before model.** Card numbers, SSNs, bank accounts, emails and phones are tokenized before
   any model sees text. Only `raw/` and `restricted/` ever hold raw content (the PCI boundary).
4. **Humans own decisions.** Low-confidence or rule-breaking facts go to analyst review. Nothing
   triggers an action on a merchant from model output alone.
5. **Ports and adapters.** OCR, speech-to-text, guard, LLM, storage and warehouse sit behind
   interfaces with local and AWS implementations.
6. **Measured.** Golden sets, gates and replayable answers decide "done"; CI blocks regressions.

## Sources

| Group | Examples | Typical formats |
| --- | --- | --- |
| Merchant | onboarding/KYB packs, prior-processor statements, dispute rebuttals, emails, calls | PDF, scans, photos, faxes, XLSX/CSV exports, ZIP uploads, EML, audio |
| External | network bulletins, ISO/partner reports, adverse media, merchant websites | HTML, PDF |
| Internal | risk analyst notes, underwriting memos, CRM notes, chat threads, case exports | Word, email, HTML, JSON chat, Markdown, voice memos |

## Pipeline

```
landing -> intake -> normalize -> guard -> classify -> extract -> resolve -> validate -> publish -> marts
           hash,      any format   PAN/PII   keywords,   schema +   MID,      grounding,  DuckDB |
           dedupe     -> pages     tokens    LLM if      evidence   fuzzy     rules,      Snowpipe
                      (OCR, ASR)             unsure      (LLM)      name      review
```

Each step is stateless: `(ctx, doc_id) -> StepResult`, reading and writing JSON through the store.
The local runner (`src/uif/runner.py`) and the Step Functions definition
(`orchestrator/statemachine.asl.json`) run the same steps in the same order, and a test enforces it.

Shared services: schema registry, model providers, merchant master, lineage/audit (`extractor_run`),
observability, golden sets and evals.

## Data model (CORE)

| Table | Grain | Key columns |
| --- | --- | --- |
| doc_envelope | document | doc_id, content_sha256, source_group, source_system, mime_type, sensitivity_tier, storage_uri |
| doc_chunk | page | chunk_id, doc_id, page, text_tokenized |
| guard_finding | finding | doc_id, kind, page, token (salted hash; raw value never stored) |
| doc_classification | document | doc_type, confidence, method, model_id |
| extracted_fact | field value | schema_name/version, field_path, value_raw, value_norm, confidence, evidence_page, evidence_quote, run_id, review_status, review_reasons |
| entity_link | document | merchant_id, mid, legal_name, match_method, match_score |
| extractor_run | model call | model_id, prompt_version, tokens, latency |
| review_task | review item | reason, fact_ids, decision, corrected_value |

Facts are long and narrow, so a new document type needs a schema, not DDL. Layers: RAW (as returned)
→ CORE (MERGE by id) → MARTS (one per use case). DuckDB locally (`sql/duckdb/core.sql`), Snowflake in
AWS (`sql/snowflake/core.sql`: stage, Snowpipe, streams, MERGE tasks, masking policies).

## Document types (built)

| Type | Fields | Rules |
| --- | --- | --- |
| processor_statement | processor, merchant, MID, period, gross volume, transactions, refunds, chargebacks (count, $), fees | fees ≤ gross, refunds ≤ gross, chargebacks ≤ transactions |
| risk_analyst_note | case id, merchant, analyst, review date, risk themes (vocabulary), recommended action, exposure | exposure ≥ 0 |
| dispute_rebuttal | case number, merchant, MID, network, reason code, amount, sale date, order, evidence types, rebuttal basis | reason code exists and belongs to the network (`data/reference/reason_codes.csv`), amount > 0 |

Unknown documents are not dropped: they're classified `unknown` and parked for review (and, later,
for the Schema Designer).

## Marts (built)

`mart_processor_statement`, `mart_underwriting_variance` (chargeback ratio, effective rate, average
ticket), `mart_analyst_themes`, `mart_pipeline_quality`, `mart_dispute_packet`,
`mart_dispute_evidence` (required vs present vs missing evidence, completeness, outcome),
`mart_dispute_win_rate`, `mart_evidence_gaps`, `v_review_queue`.

## Agents and skills

| Component | Kind | Status |
| --- | --- | --- |
| Intake, Normalizer (all formats, OCR, ASR), Sensitivity Guard, Publisher | skills (deterministic) | built |
| Classifier (keywords first, LLM when unsure) | agent | built |
| Schema Extractor | agent | built: rules baseline, handoff (Claude Code/Copilot), Claude API, Bedrock, Ollama |
| Entity Resolver (MID exact, fuzzy name) | skill (+ LLM tiebreak planned) | built; tiebreak planned |
| Validator (grounding, value-in-quote, rules, per-item evidence, source quality) | agent + rules | built |
| Signal Builder, Analyst Q&A, Schema Designer | agents | planned (Phase 3) |
| Synthetic generators (golden, formats, audio) | skills | built |

Claude Code scaffolding: `CLAUDE.md`; skills `new-doc-type`, `run-golden-eval`,
`extraction-debugger`, `snowflake-ddl`, `aws-deploy-check`, `agent-extract`; subagents
`schema-reviewer`, `pii-auditor`, `prompt-tuner`.

## Runtimes

| Concern | Laptop | AWS |
| --- | --- | --- |
| Store | local folder | S3 (SSE-KMS); `raw/` + `restricted/` locked down |
| OCR | pdfplumber + tesseract | Textract (sync / async multi-page) |
| Speech | whisper.cpp → pocketsphinx (flagged) | Transcribe with speaker labels |
| Guard | regex + Luhn (+ salted tokens) | same, plus Comprehend PII |
| LLM | handoff (Claude Code / Copilot), Claude API gateway, Ollama, rules | Bedrock (Claude) |
| Orchestration | Python runner | Step Functions, Lambda (light steps), ECS Fargate (normalize, extract) |
| Warehouse | DuckDB | Snowflake via Snowpipe |

## Roadmap and gates

| Phase | Scope | Exit gate |
| --- | --- | --- |
| 0 Foundations | contracts, envelope, providers, local runner, two doc types | Gate A: golden sets pass locally; contract tests green: **met** |
| 1 Pilot doc types | statements, rebuttals, analyst notes; review UI; marts | Gate B: F1 and grounding targets met on a model-backed extractor; zero PII leakage. Met on synthetic data; real redacted samples pending |
| 2 AWS dev + shadow | Step Functions, Textract, Bedrock, Snowflake | Gate C: security, PCI, model-risk sign-off + Bedrock parity report |
| 3 Production + scale | more sources via Schema Designer, Q&A agent, signals into risk queues | |

Gates (in `src/uif/evals.py`): PII leakage = 0, grounding ≥ 0.99, classification ≥ 0.95,
required-field F1 ≥ 0.90; adversarial documents must pass. Parity: required-field agreement ≥ 0.95.
