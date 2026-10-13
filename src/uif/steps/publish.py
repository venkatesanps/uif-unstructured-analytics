"""Step 8: idempotent load of CORE tables (DuckDB locally, Snowpipe stage in AWS)."""

from __future__ import annotations

import hashlib
import json

from uif.context import Context
from uif.contracts import (
    Classification,
    DocEnvelope,
    EntityLink,
    Extraction,
    GuardedDoc,
    StepResult,
    Validated,
)


def run(ctx: Context, doc_id: str) -> StepResult:
    wh = ctx.providers.warehouse
    env = ctx.get_model("envelope", DocEnvelope, doc_id=doc_id)
    cls = ctx.get_model("classification", Classification, doc_id=doc_id)
    ext = ctx.get_model("extraction", Extraction, doc_id=doc_id)
    link = ctx.get_model("entity", EntityLink, doc_id=doc_id)
    val = ctx.get_model("validated", Validated, doc_id=doc_id)
    guarded = ctx.get_model("guarded", GuardedDoc, doc_id=doc_id)

    counts = {}
    counts["doc_envelope"] = wh.upsert("doc_envelope", [env.model_dump(mode="json")], ["doc_id"])
    counts["doc_chunk"] = wh.upsert("doc_chunk", [
        {"chunk_id": hashlib.sha256(f"{doc_id}|{p.page}".encode()).hexdigest()[:16], "doc_id": doc_id,
         "page": p.page, "text_tokenized": p.text} for p in guarded.pages], ["chunk_id"])
    counts["guard_finding"] = wh.upsert("guard_finding", [
        {"doc_id": doc_id, "seq": i, "kind": f.kind, "page": f.page, "token": f.token}
        for i, f in enumerate(guarded.findings)], ["doc_id", "seq"])
    counts["doc_classification"] = wh.upsert("doc_classification", [cls.model_dump(mode="json")], ["doc_id"])
    counts["extractor_run"] = wh.upsert("extractor_run", [ext.run.model_dump(mode="json")], ["run_id"])
    counts["entity_link"] = wh.upsert("entity_link", [link.model_dump(mode="json")], ["doc_id"])
    facts = []
    for f in val.facts:
        row = f.model_dump(mode="json")
        row["value_raw"], row["value_norm"] = json.dumps(row["value_raw"]), json.dumps(row["value_norm"])
        facts.append(row)
    counts["extracted_fact"] = wh.upsert("extracted_fact", facts, ["fact_id"])
    tasks = []
    for t in val.review_tasks:
        row = t.model_dump(mode="json")
        row["corrected_value"] = None if row["corrected_value"] is None else json.dumps(row["corrected_value"])
        tasks.append(row)
    counts["review_task"] = wh.upsert("review_task", tasks, ["task_id"])
    ctx.put_json("published", counts, doc_id=doc_id)
    return StepResult(doc_id=doc_id, step="publish", ok=True, output_key=ctx.key("published", doc_id=doc_id),
                      detail=f"{counts['extracted_fact']} facts, {counts['review_task']} tasks")
