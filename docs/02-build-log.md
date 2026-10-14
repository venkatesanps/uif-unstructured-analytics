# 02 Build log

In order, with the commit for each step. All work was done on 2026-10-13.

## 1. Design

Wrote the framework design: layered pipeline, canonical data model, agent/skill roster, local vs AWS
mapping, testing strategy, governance, and a four-phase roadmap with gates. Lives as a Claude Doc
(link in [README](README.md)); the essentials are in [01 Design](01-design.md).

## 2. Phase 0 scaffold: `a70a1a9`

- Pydantic step contracts; provider ports with local adapters (filesystem, pdfplumber + tesseract,
  regex/Luhn guard, rules extractor, Ollama, DuckDB) and AWS adapters (S3, Textract, Comprehend,
  Bedrock, Snowpipe staging).
- Eight steps (intake → publish), local runner, Lambda handler, Step Functions definition, Dockerfile
  with Lambda and ECS targets.
- Two doc types (processor statement, risk analyst note); synthetic generator with labels: three
  statement layouts (one unseen), a scanned PDF, planted PAN/SSN, prompt-injection text, an unknown
  flyer.
- Evals with gates; review workflow (`uif review`, Streamlit UI, corrections logged to the golden set).
- Claude Code scaffolding: `CLAUDE.md`, five skills, three subagents.
- Result: gates passed with the rules baseline; the unseen layout and unknown type went to review.

## 3. Dispute rebuttals: `49aeb31`

- Third doc type `dispute_rebuttal`: PDF packets and emails with attachments (each attachment
  becomes labelled pages; image attachments OCR'd).
- Reason-code reference table and two reference rules (`in_ref`, `ref_pair`).
- Marts: dispute packet, evidence completeness, win rate, evidence gaps (DuckDB + Snowflake).
- Fixes found while building: per-item evidence check (an injected "mark all evidence complete"
  could pass with one quote), vocabulary-aware enum check, PAN regex no longer matches inside long
  digit runs, Textract staging moved under `restricted/`, DuckDB TRY_CAST in pivots.

## 4. Claude at work: `fc428d0`

Context: no Ollama at work; Claude and Copilot on the laptop; Bedrock in AWS.

- **Agent handoff** (`--llm handoff`): the pipeline writes tokenized extraction requests; Claude Code
  (`/agent-extract`) or Copilot (prompt file) answers per `AGENT_EXTRACT.md`; a rerun resumes.
- **Claude API provider** (`--llm anthropic`): direct or via a gateway (base URL, bearer auth, extra
  headers).
- Claude/Bedrock adapters use `tool_choice: auto` plus JSON-text fallback: forced tools return 400 on
  the newest Claude models, and strict mode's 16-union limit is too small for these schemas.
- Ran the golden set through handoff with Claude answering: F1 1.0 (see [03 Results](03-results.md)).
- Fixes: OCR-split emails escaped the guard; `uif reguard` cleans stored copies after any guard
  change; golden labels corrected to ground truth.
- Saved answers in `evals/` and `make eval-replay` replays them in CI.

## 5. Bedrock parity check: `53d9239`

- `uif handoff answer --with bedrock` answers the same requests with Bedrock (verbatim prompts and
  schema); `uif handoff export/import` moves bundles between laptop and AWS (`store:` keys on S3).
- `uif parity diff` gives field-by-field agreement, disagreements with both quotes, and both sides
  scored against labels → markdown/JSON report. Gate: required-field agreement ≥ 0.95.
- Verified end to end with the rules baseline standing in for Bedrock (correctly failed at 90.5%);
  the exact ECS command from `PARITY.md` tested against mocked S3.
- Fix: bundle import uses the regex guard in every runtime (Comprehend would refuse names).

## 6. Delivery to work

- Three standalone zips under 250 KB were produced, but the firm's mail filter blocked the
  attachment (policy violation, not size). No workaround was attempted.
- Instead, the repo was pushed to GitHub: `venkatesanps/uif-unstructured-analytics` (commit author
  is the personal Gmail address; can be rewritten to the GitHub no-reply address on request).

## 7. Every common format: `fa3b7dc`

- Readers: DOCX (XML, no Word needed), XLSX (cell-format aware), CSV, JSON (chat transcript or
  `Key: value`), ZIP (recursive, zip-bomb limits), multi-page fax TIFF; HTML tables read as
  `Label: value`; forwarded emails labelled by subject.
- `samples/formats/`: 14 labeled samples (photo, fax, Excel with planted PAN, CSV, ZIP of DOCX+PDF+JPEG,
  forwarded EML, portal JSON, Word memo with planted SSN, HTML email, case export, chat JSON,
  Markdown, news page, bulletin).
- Rules and Claude runs saved in `evals/formats/`; `make eval-samples`.

## 8. Audio: `01f7763`

- `samples/audio/`: voice memo (WAV), two-speaker merchant call with a card number read aloud (WAV),
  noisy voicemail (MP3), dictated update (M4A), generated with espeak-ng (macOS `say` when present).
- Transcriber chain: whisper.cpp → pocketsphinx (flagged low accuracy → every fact reviewed);
  AWS Transcribe adapter with speaker labels, everything under `restricted/`.
- Spoken digits become numerals before the guard (card/phone read aloud get tokenized); validator
  accepts spoken amounts, dates and identifiers; Transcribe-style `spk_0` speaker labels.
- Three runs saved in `evals/audio/`; `make eval-audio`.

## 9. Reference docs

This `docs/` folder.

## Test suite growth

28 → 36 → 44 → 51 → 72 → 86 tests (plus one live-Ollama test that skips without a server).
