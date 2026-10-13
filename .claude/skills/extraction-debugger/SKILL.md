---
name: extraction-debugger
description: Explain why a UIF document produced a wrong, missing or reviewed fact - replays its steps and shows classification, extractor output, evidence and the validator reason. Use when given a doc_id or file name and a field that looks wrong.
---

# Debug one document

1. Resolve the doc_id: `uif sql "select doc_id, file_name from doc_envelope where file_name like '%<name>%'"`.
2. Read, in order, from the store (`.uif/store/` locally): `envelope/`, `classification/`,
   `extraction/`, `entity/`, `validated/` `<doc_id>.json`. Read `guarded/<doc_id>.json` for page text.
   **Never read `raw/` or `restricted/`.**
3. For the field in question show: classification (type, confidence, method), extractor value/page/
   quote/confidence, normalized value, review reasons, and the guarded page text around the quote.
4. Diagnose with the decision tree:
   - wrong type → keywords in `schema.json` `classify` or LLM classifier.
   - value null → rules: hint regex didn't match (test it against the page text); LLM: prompt or truncation.
   - `not_grounded` → quote not on cited page: model paraphrased or cited the wrong page.
   - `value_not_in_quote` → number in value differs from the quote: normalization or model error.
   - `rule:<id>` → cross-field rule; check both fields before blaming the model.
   - `low_confidence` → threshold `review_below` vs model calibration.
5. Re-run just that step after a fix: `uif step extract --doc-id <id>` then `validate`, `publish`.
6. If the fix is a schema/prompt change, run the `run-golden-eval` skill before finishing.
