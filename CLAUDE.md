# UIF — operating rules for coding agents

Unstructured-data intelligence framework for merchant services: any document → evidence-linked
facts → Snowflake analytics. Design doc: "Merchant Services Unstructured-Data Analytics Framework".

## Non-negotiables
1. **No real merchant data on a laptop.** Local runs use `synthetic/` or fully redacted files only.
2. **Guard before model.** Nothing under `raw/` or `restricted/` is ever passed to an LLM, logged, or
   published. Only `guarded/` text reaches a model. Never weaken `RegexGuard` patterns without a test.
3. **Evidence or it didn't happen.** Every extracted value carries page + verbatim quote + confidence.
   Do not relax grounding or `value_in_quote` checks in `steps/validate.py` to make a test pass.
4. **Schema-first.** New behaviour for a document type goes in `registry/doc_types/<type>/`
   (schema.json, prompt.md), not in step code. Bump `version` / `prompt_version` when you change them.
5. **Steps are stateless and runtime-agnostic.** A step takes `(ctx, doc_id)`, reads/writes through
   `ctx.store`, returns `StepResult`. No `boto3`, `requests` or file paths inside steps; those belong
   in `providers/`.
6. **Gates are the definition of done.** `make ci` must pass: unit, contract, golden, adversarial,
   integration, aws (moto). Never edit thresholds in `evals.GATES` to get green.

## Layout
- `src/uif/contracts.py` — pydantic step I/O. Change here = change everywhere; update tests.
- `src/uif/providers/` — `local.py` (fs, pdfplumber/tesseract, regex guard, rules, Ollama, DuckDB),
  `aws.py` (S3, Textract, Comprehend, Bedrock, Snowpipe stage). Factory in `__init__.py`.
- `src/uif/steps/` — intake, normalize, guard, classify, extract, resolve, validate, publish.
- `src/uif/runner.py` local orchestrator; `orchestrator/statemachine.asl.json` AWS orchestrator.
  Keep step order identical (a contract test enforces it).
- `sql/duckdb/core.sql` and `sql/snowflake/core.sql` — same tables and columns. Change both.
- `synth.py` — labeled synthetic documents; `evals.py` — metrics + gates.

## Commands
```
make setup          # venv + deps
make synth          # regenerate synthetic/ and data/merchant_master.csv
make run            # process synthetic/ locally with the rules baseline
make eval           # golden metrics + gates (LLM=ollama make eval for the local model)
make test           # full suite (Ollama tests skip if no server)
make ci             # what the pipeline runs
```

## When adding a document type
Use the `new-doc-type` skill. It scaffolds schema, prompt, synthetic generator and golden tests,
and the `schema-reviewer` subagent checks the result.

## Lessons
Append to `LESSONS_LEARNED.md` when something surprised you (a format quirk, a false-positive in the
guard, a prompt change that moved F1). One line, dated, with the fix.
