"""Step 5: fill the doc-type schema. The model sees tokenized text only."""

from __future__ import annotations

import uuid

from uif.context import Context
from uif.contracts import Classification, Extraction, ExtractorRun, FieldValue, GuardedDoc, StepResult


def run(ctx: Context, doc_id: str) -> StepResult:
    cls = ctx.get_model("classification", Classification, doc_id=doc_id)
    llm = ctx.providers.llm
    run_id = uuid.uuid4().hex[:16]
    if cls.doc_type not in ctx.registry:
        ext = Extraction(doc_id=doc_id, doc_type=cls.doc_type, schema_version="-", fields={},
                         run=ExtractorRun(run_id=run_id, doc_id=doc_id, agent="extractor",
                                          model_id="none", prompt_version="-"))
        key = ctx.put_model("extraction", ext, doc_id=doc_id)
        return StepResult(doc_id=doc_id, step="extract", ok=True, output_key=key, detail="skipped: unknown type")
    doc_type = ctx.registry.get(cls.doc_type)
    doc = ctx.get_model("guarded", GuardedDoc, doc_id=doc_id)
    out = llm.extract(doc.pages, doc_type)
    ext = Extraction(
        doc_id=doc_id,
        doc_type=doc_type.name,
        schema_version=doc_type.version,
        fields={k: FieldValue(**v) for k, v in out.fields.items()},
        run=ExtractorRun(run_id=run_id, doc_id=doc_id, agent="extractor", model_id=out.usage.model_id,
                         prompt_version=doc_type.prompt_version, tokens_in=out.usage.tokens_in,
                         tokens_out=out.usage.tokens_out, latency_ms=out.usage.latency_ms),
    )
    key = ctx.put_model("extraction", ext, doc_id=doc_id)
    filled = sum(1 for f in ext.fields.values() if f.value not in (None, []))
    return StepResult(doc_id=doc_id, step="extract", ok=True, output_key=key,
                      detail=f"{filled}/{len(ext.fields)} fields via {out.usage.model_id}")
