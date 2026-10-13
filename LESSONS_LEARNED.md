# Lessons learned

One line per lesson, newest first: date — what happened — what we changed.

- 2026-10-13 — "BLUE HARBOR COFFEE, L.L.C." failed fuzzy match because the suffix regex didn't see dotted "L.L.C." — strip dots and map "&" to "and" before suffix removal (`steps/resolve.py`).
- 2026-10-13 — Long single lines drawn with reportlab run off the page and pdfplumber drops the overflow — synthetic generator wraps lines at 95 chars.
- 2026-10-13 — Merchant IDs can be 12–16 digits and occasionally pass Luhn — PAN detection also requires a card-brand prefix (2–6) and skips digits right after MID/Merchant ID/TID labels.
- 2026-10-13 — A model that obeys injected text can quote the injection itself, so grounding alone does not catch it — cross-field rules (fees ≤ gross, refunds ≤ gross) are what flag it; keep rules on every money field.
