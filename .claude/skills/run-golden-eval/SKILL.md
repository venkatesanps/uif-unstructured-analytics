---
name: run-golden-eval
description: Run UIF golden-set evaluation for one provider (rules, ollama, bedrock), compare with the last baseline, and explain any regression field by field. Use after changing a schema, prompt, guard, validator or model.
---

# Golden eval

1. Pick the provider: `rules` (default, offline), `ollama` (needs `ollama serve` and the model in
   `config/local.yaml`), or `bedrock` (AWS dev account only, `--runtime aws`).
2. Run: `LLM=<provider> make eval > .uif/eval-<provider>.json` (non-zero exit = a gate failed).
3. Compare with the baseline in `evals/baseline-<provider>.json` if present:
   - headline metrics: classification_accuracy, required_f1, field_f1, grounding_rate, pii_leakage,
     review_rate, adversarial_pass
   - `by_field_f1`: list every field whose F1 dropped by ≥ 0.02
   - `documents_detail[].wrong`: show expected vs got for the dropped fields (values only; never print
     page text outside `guarded/`)
4. Explain each regression in one line with its likely cause (prompt change, hint regex, OCR, rule).
5. If the change is an intended improvement and gates pass, offer to update the baseline file.
   Never lower `evals.GATES`.

Report as a short table: metric | baseline | now | delta, then the per-field list.
