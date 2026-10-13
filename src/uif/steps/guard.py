"""Step 3: tokenize card numbers and PII. Nothing downstream ever reads restricted/."""

from __future__ import annotations

from uif.context import Context
from uif.contracts import DocEnvelope, GuardedDoc, NormalizedDoc, SensitivityTier, StepResult

_RESTRICTED_KINDS = {"pan", "ssn", "bank_account", "passport", "driver_id"}


def run(ctx: Context, doc_id: str) -> StepResult:
    norm = ctx.get_model("normalized", NormalizedDoc, doc_id=doc_id)
    try:
        pages, findings = ctx.providers.guard.scan(norm.pages)
    except Exception as exc:  # fail closed: a doc we could not scan never reaches a model
        guarded = GuardedDoc(doc_id=doc_id, pages=[], sensitivity_tier=SensitivityTier.restricted, quarantined=True)
        ctx.put_model("guarded", guarded, doc_id=doc_id)
        return StepResult(doc_id=doc_id, step="guard", ok=False, halt=True, detail=f"quarantined: {exc}")
    kinds = {f.kind for f in findings}
    tier = SensitivityTier.restricted if kinds & _RESTRICTED_KINDS else (
        SensitivityTier.confidential if findings else SensitivityTier.internal)
    guarded = GuardedDoc(doc_id=doc_id, pages=pages, findings=findings, sensitivity_tier=tier)
    key = ctx.put_model("guarded", guarded, doc_id=doc_id)
    env = ctx.get_model("envelope", DocEnvelope, doc_id=doc_id)
    env.sensitivity_tier = tier
    ctx.put_model("envelope", env, doc_id=doc_id)
    detail = ", ".join(f"{k}={sum(1 for f in findings if f.kind == k)}" for k in sorted(kinds)) or "clean"
    return StepResult(doc_id=doc_id, step="guard", ok=True, output_key=key, detail=detail)
