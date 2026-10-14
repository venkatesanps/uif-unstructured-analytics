# 03 Results

All runs on synthetic data, 2026-10-13. Raw numbers: `evals/**/baseline-*.json`.

## How much to trust these

- **Rules baseline:** deterministic regex hints written against the synthetic layouts. Its perfect
  scores on known layouts prove the plumbing, not accuracy.
- **Claude via handoff:** answers written by Claude (Opus 5.5) in the build session, reading only the
  tokenized request files. The same session wrote the generators and the documents are clean. Treat
  1.0 as "the path works and the validator accepts correct answers", **not** as an independent accuracy
  measurement.
- **Real accuracy** comes from your agent at work on redacted real samples, and from Bedrock in AWS
  dev (parity report).

## Golden set: 19 docs (statements, rebuttals, analyst notes, one unknown)

| Metric | Rules | Claude (handoff) | Gate |
| --- | --- | --- | --- |
| Classification accuracy | 1.00 | 1.00 | ≥ 0.95 |
| Required-field F1 | 0.950 | 1.00 | ≥ 0.90 |
| All-field F1 | 0.948 | 1.00 | reported |
| Grounding rate | 1.00 | 1.00 | ≥ 0.99 |
| PII/PAN leakage | 0 | 0 | = 0 |
| Merchant linking | 0.947 | 1.00 | reported |
| Facts sent to review | 0% | 0.6% (sale date with no year) | reported |
| Injection docs | pass | pass | must pass |

Rules can't read the unseen statement layout or the freeform rebuttal email; both go to review
instead of being guessed. Claude reads both.

## Parity tooling check (rules standing in for Bedrock)

Required-field agreement 90.5% → **FAIL**, which is correct: the report pinpointed exactly the two
layouts rules can't read. The real Bedrock run is pending (see [07 Open items](07-open-items.md)).

## Formats: 14 docs, one per format

| Metric | Rules | Claude (handoff) |
| --- | --- | --- |
| Classification accuracy | 1.00 | 1.00 |
| Required-field F1 | 0.92 | 1.00 |
| All-field F1 | 0.945 | 1.00 |
| Merchant linking | 0.857 | 1.00 |
| PII/PAN leakage (PAN in XLSX, SSN in DOCX, emails/phones) | 0 | 0 |

Rules misses anything not written as `Label: value`: Markdown bold labels, the chat transcript, the
portal JSON (unformatted amount, nested merchant name).

## Audio: 4 recordings

| Metric | Real recognizer (pocketsphinx) | Reference transcript + rules | Reference transcript + Claude |
| --- | --- | --- | --- |
| Classification accuracy | 0.25 | 1.00 | 1.00 |
| Required-field F1 | 0.00 | 0.00 | 1.00 |
| Merchant linking | 0.25 | 0.25 | 1.00 |
| Leakage (card and phone read aloud) | 0 | 0 | 0 |
| Facts auto-accepted from bad transcripts | 0 | n/a | n/a |

pocketsphinx was the only recognizer installable in the build sandbox (model hosts blocked) and it
can't follow synthetic voices. It proves the safety path (flagged, nothing trusted, nothing leaked).
"Reference transcript" replays the exact script as a stand-in for whisper.cpp or Transcribe. Real
recognition accuracy is still unmeasured.

## Reproduce

```bash
make ci            # tests + golden eval + replays (golden, formats, audio)
make eval          # rules on golden
make eval-replay   # saved Claude answers on golden
make eval-samples  # formats: rules + saved Claude answers
make eval-audio    # audio: reference transcripts + saved Claude answers
```
