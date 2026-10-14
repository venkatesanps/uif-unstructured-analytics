# 05 Decisions and lessons

## Key decisions

| Decision | Why |
| --- | --- |
| Facts stored long and narrow (one row per field) | New document types need a schema, not DDL; marts pivot what each use case needs |
| Evidence (page + verbatim quote) required on every value | Makes every number auditable, and lets the validator catch invented or injected values |
| Guard before any model; only `raw/` and `restricted/` hold raw text | Keeps PCI scope to intake + guard; models, logs, warehouse see tokens only |
| Tokens are salted hashes | Same card/email → same token across documents (joinable), raw value never stored |
| Rules baseline kept forever | Pipeline and tests run with no model; a model's gain is measurable against it |
| Unknown documents parked, not dropped | Feeds the planned Schema Designer; nothing silently lost |
| Agent handoff provider | Works at the firm with Claude Code or Copilot: no API key, no local model |
| `tool_choice: auto` + JSON-text fallback for Claude/Bedrock | Forced tool choice returns 400 on the newest Claude models; strict mode caps nullable unions at 16 |
| Bedrock answers the *same* requests as the local agent | Parity measures model differences, not prompt differences |
| Bundle checks use the regex/Luhn guard in every runtime | Comprehend flags names and would refuse every synthetic request |
| Format and audio samples kept apart from the golden set | Adding formats never shifts golden request IDs; sets stay environment-independent |
| Low-accuracy transcription is flagged, never trusted | A weak recognizer can't feed auto-accepted facts |
| Transcribe-style `spk_0` speaker labels | Recognizers don't know roles; role names collided with field labels |
| Reason-code evidence requirements are placeholders | The real list belongs to the disputes team; flagged in `data/README.md` |

## Bugs the tests caught (and fixes)

Grouped by area. `LESSONS_LEARNED.md` has the same list, newest first.

**Guard / PCI**
- MIDs can be 12–16 digits and pass Luhn → PAN detection also needs a card-brand prefix and skips
  digits after MID/TID/invoice labels.
- A 16-digit window inside a long grouped digit run (container/tracking IDs) passed Luhn → a PAN may
  not start or end inside a longer run.
- OCR split an email ("disputes @ lakeside-example.com") and the guard missed it → pattern tolerates
  single spaces around `@` and dots, but needs an alphabetic TLD so "qty 2 @ 5.00" is left alone.
- Fixing the guard didn't clean stored copies → `uif reguard`.
- Textract async staging wrote raw bytes outside the boundary → `restricted/ocr-staging/`.
- A card number read aloud stayed as words in a transcript → spoken digits become numerals before the
  guard.

**Validator / prompt injection**
- A model obeying injected text can quote the injection itself → cross-field rules (fees ≤ gross,
  refunds ≤ gross) catch it.
- One grounded quote vouched for a whole evidence list ("mark all evidence complete") → every list
  item needs its own phrase in the document.
- Vocabulary-derived enums never appear verbatim → check the category's phrases instead.
- Transcripts: canonical answers ("CB-2026-814273" from "C B 2026 814273", 13.1 from "thirteen point
  one") failed value-in-quote → compare letters and digits only, and accept spoken numbers; wrong
  values still fail.

**Readers**
- Long reportlab lines ran off the page and pdfplumber dropped the overflow → wrap at 95 chars.
- HTML tables flattened and lost labels → `<th>`/`<td>` read as `Label: value`.
- Forwarded emails appeared as `attachment-1` → labelled `forwarded email: <subject>`.
- Tesseract's trailing form feed changed a golden request ID when TIFF splitting was added → the drift
  test caught it; re-pinned by procedure.

**Data and labels**
- Dotted "L.L.C." broke fuzzy merchant matching → strip dots, map `&` to "and".
- A golden label said "no merchant" because the baseline couldn't find one → labels are ground truth.
- DuckDB evaluates CAST before an aggregate FILTER → TRY_CAST in pivot marts.
- The leak check only scanned planted IDs, so it missed the OCR-split email → planted contact emails
  added to labels.

**Packaging**
- Zip checksum paths didn't match the instructions, and git needs empty directories zip drops → fixed
  before delivery (later superseded by GitHub).
