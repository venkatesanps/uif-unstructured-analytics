"""Step 2: any format -> pages of text. Output is restricted (still contains raw PII)."""

from __future__ import annotations

from uif.context import Context
from uif.contracts import DocEnvelope, NormalizedDoc, StepResult


def run(ctx: Context, doc_id: str) -> StepResult:
    env = ctx.get_model("envelope", DocEnvelope, doc_id=doc_id)
    data = ctx.store.get_bytes(ctx.key("raw", doc_id=doc_id, file_name=env.file_name))
    try:
        pages, method = ctx.providers.ocr.to_pages(data, env.mime_type, env.file_name)
    except NotImplementedError as exc:
        return StepResult(doc_id=doc_id, step="normalize", ok=False, halt=True, detail=str(exc))
    if not any(p.text.strip() for p in pages):
        return StepResult(doc_id=doc_id, step="normalize", ok=False, halt=True, detail="no text recovered")
    env.page_count = len(pages)
    ctx.put_model("envelope", env, doc_id=doc_id)
    key = ctx.put_model("normalized", NormalizedDoc(doc_id=doc_id, pages=pages, method=method), doc_id=doc_id)
    return StepResult(doc_id=doc_id, step="normalize", ok=True, output_key=key, detail=method)
