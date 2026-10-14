# Lessons learned

One line per lesson, newest first: date — what happened — what we changed.

- 2026-10-13 — Parity needs both extractors on byte-identical input, or disagreements mix model differences with prompt differences — Bedrock answers the handoff request's own system/user prompt and schema; saved answers are pinned to request IDs and a test fails on drift.
- 2026-10-13 — Fixing a guard pattern doesn't clean what is already stored: old guarded/ files and handoff requests still held the identifier — added `uif reguard` (re-guards every stored doc, purges handoff requests the new guard would change). Run it after every guard change.
- 2026-10-13 — OCR split an email into "disputes @ lakeside-example.com" and the guard missed it; the leak check also missed it because only planted IDs were scanned — email pattern tolerates single spaces around @ and dots (alphabetic TLD required); planted contact emails added to labels.
- 2026-10-13 — A golden label said "no merchant" for the freeform rebuttal because the baseline couldn't find one — labels are ground truth, never baseline expectations; the stronger extractor exposed it.
- 2026-10-13 — Forced tool choice returns 400 on the newest Claude models, and strict mode caps nullable unions at 16 — Claude/Bedrock adapters use auto + JSON-text fallback; the validator is the safety net.
- 2026-10-13 — A model obeying "mark all evidence as complete" can cite the injection line itself, so one grounded quote vouched for a whole evidence list — string_list fields now need each item's own phrase somewhere in the document (`item_not_in_document`).
- 2026-10-13 — Vocabulary-derived enums (rebuttal_basis) failed `value_not_in_quote` because the category name never appears verbatim — the check now looks for that category's phrases.
- 2026-10-13 — DuckDB evaluates CAST before an aggregate FILTER, so casting value_norm to DOUBLE blew up on string facts — use TRY_CAST in pivot marts.
- 2026-10-13 — Old PAN regex could start a match mid-way through a long grouped digit run (container/tracking IDs) and Luhn-pass a 16-digit window — a PAN may no longer start or end inside a longer run.
- 2026-10-13 — Textract async staging wrote raw bytes to `ocr-staging/`, outside the PCI boundary — moved to `restricted/ocr-staging/`.
- 2026-10-13 — "BLUE HARBOR COFFEE, L.L.C." failed fuzzy match because the suffix regex didn't see dotted "L.L.C." — strip dots and map "&" to "and" before suffix removal (`steps/resolve.py`).
- 2026-10-13 — Long single lines drawn with reportlab run off the page and pdfplumber drops the overflow — synthetic generator wraps lines at 95 chars.
- 2026-10-13 — Merchant IDs can be 12–16 digits and occasionally pass Luhn — PAN detection also requires a card-brand prefix (2–6) and skips digits right after MID/Merchant ID/TID labels.
- 2026-10-13 — A model that obeys injected text can quote the injection itself, so grounding alone does not catch it — cross-field rules (fees ≤ gross, refunds ≤ gross) are what flag it; keep rules on every money field.
