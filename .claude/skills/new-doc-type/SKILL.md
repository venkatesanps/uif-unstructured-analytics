---
name: new-doc-type
description: Add a new document type to the UIF registry — schema, prompt, synthetic generator, golden labels and tests. Use when asked to support a new kind of document (e.g. dispute rebuttal, KYB pack, network bulletin).
---

# Add a document type

Inputs to collect first (ask if missing): type name (snake_case), source group (merchant/external/internal),
2–5 example documents or a description of their layouts, the fields analysts need, which fields are required.

## Steps
1. **Read the neighbours.** Open `registry/doc_types/processor_statement/schema.json` and
   `risk_analyst_note/schema.json` for conventions (field types: string, money, integer, percent, date,
   date_range, enum, string_list).
2. **Write `registry/doc_types/<type>/schema.json`:**
   - `description` one sentence (used by the LLM classifier).
   - `classify.keywords`: 6–8 lower-case phrases that appear in ≥ 60% of these documents and rarely
     elsewhere. Check they don't collide with other types' keywords.
   - each field: `type`, `description`, optional `review_below` (use 0.85 for money/decision fields),
     `hints` (regex with ONE capture group, for the offline baseline), `values` for enums,
     `vocabulary` for string_list.
   - `vocabulary` also works on `enum` fields whose value is a category the text never states
     verbatim (see `dispute_rebuttal.rebuttal_basis`); the validator then checks the quote for that
     category's phrases, and every `string_list` item must have its own phrase in the document.
   - `required` and cross-field `rules` (lte/gte/between/in, plus `in_ref` / `ref_pair` against a
     lookup in `data/reference/<name>.csv`). Every money field should sit in at least one rule; rules
     are what catch a model that obeyed injected text.
   - `version` and `prompt_version` start at 1.0.0.
3. **Write `prompt.md`:** domain guidance only (what the field means, common label variants, sign
   conventions). Never put output-format instructions here; `llm_common.py` owns those.
4. **Extend `src/uif/synth.py`:** a generator for ≥ 2 layouts, ≥ 1 layout with labels the hints do NOT
   cover (it must land in review), one with a planted PAN or SSN, one with injection text. Emit labels.
5. **Run:** `make synth && make eval`. Fix hints until gates pass for covered layouts; the unseen layout
   must show `missing_required` in review tasks, not wrong values.
6. **Add marts** if analysts need typed columns: a view in `sql/duckdb/core.sql` and the same in
   `sql/snowflake/` (use the `snowflake-ddl` skill).
7. **Review:** run the `schema-reviewer` subagent on the new folder, then `make ci`.
8. Append anything surprising to `LESSONS_LEARNED.md`.

## Done when
- `make ci` is green, the new type appears in `mart_pipeline_quality`, and the unseen-layout document
  is routed to review.
