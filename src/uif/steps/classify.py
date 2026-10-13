"""Step 4: doc type. Cheap keyword pass first; the model is asked only when unsure."""

from __future__ import annotations

from uif.context import Context
from uif.contracts import Classification, GuardedDoc, StepResult
from uif.providers.local import RulesExtractor
from uif.registry import TAXONOMY_VERSION


def run(ctx: Context, doc_id: str) -> StepResult:
    doc = ctx.get_model("guarded", GuardedDoc, doc_id=doc_id)
    candidates = [ctx.registry.get(n) for n in ctx.registry.names()]
    first = RulesExtractor().classify(doc.pages, candidates)
    result = Classification(doc_id=doc_id, doc_type=first.doc_type, confidence=first.confidence,
                            taxonomy_version=TAXONOMY_VERSION, method="keywords", model_id="rules-v1")
    llm = ctx.providers.llm
    if first.confidence < ctx.min_classify and not isinstance(llm, RulesExtractor):
        second = llm.classify(doc.pages, candidates)
        result = Classification(doc_id=doc_id, doc_type=second.doc_type, confidence=second.confidence,
                                taxonomy_version=TAXONOMY_VERSION, method="llm", model_id=llm.model_id)
    if result.confidence < ctx.min_classify:
        result.doc_type = "unknown"
    key = ctx.put_model("classification", result, doc_id=doc_id)
    return StepResult(doc_id=doc_id, step="classify", ok=True, output_key=key,
                      detail=f"{result.doc_type} ({result.confidence:.2f}, {result.method})")
