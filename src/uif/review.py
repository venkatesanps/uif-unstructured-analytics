"""Human review decisions. Kept out of the UI so it is testable and reusable from
A2I callbacks in AWS. Every decision is recorded; corrections feed the golden set."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from uif.context import Context
from uif.contracts import ReviewStatus, Validated, utcnow
from uif.values import normalize


def open_tasks(ctx: Context, limit: int = 100) -> list[dict[str, Any]]:
    rows = ctx.providers.warehouse.query(
        "select task_id, doc_id, file_name, doc_type, reason from v_review_queue limit ?", [limit])
    return [dict(zip(["task_id", "doc_id", "file_name", "doc_type", "reason"], r)) for r in rows]


def apply_decision(ctx: Context, task_id: str, decision: str, reviewer: str,
                   corrected_value: Any = None) -> dict[str, Any]:
    status = ReviewStatus(decision)
    if status not in (ReviewStatus.accepted, ReviewStatus.corrected, ReviewStatus.rejected):
        raise ValueError("decision must be accepted, corrected or rejected")
    wh = ctx.providers.warehouse
    row = wh.query("select doc_id, fact_ids from review_task where task_id = ?", [task_id])
    if not row:
        raise KeyError(task_id)
    doc_id, fact_ids = row[0][0], json.loads(row[0][1] or "[]")
    val = ctx.get_model("validated", Validated, doc_id=doc_id)
    corrections = []
    for fact in val.facts:
        if fact.fact_id not in fact_ids:
            continue
        fact.review_status = status
        if status == ReviewStatus.corrected:
            corrections.append({"doc_id": doc_id, "doc_type": fact.schema_name, "field": fact.field_path,
                                "model_value": fact.value_norm, "corrected_value": corrected_value,
                                "evidence_quote": fact.evidence_quote, "reviewer": reviewer, "ts": utcnow()})
            fact.value_raw = corrected_value
            fact.value_norm = normalize(fact.data_type, corrected_value)
        wh.upsert("extracted_fact", [fact.model_dump(mode="json") | {
            "value_raw": json.dumps(fact.value_raw), "value_norm": json.dumps(fact.value_norm)}], ["fact_id"])
    for t in val.review_tasks:
        if t.task_id == task_id:
            t.decision, t.corrected_value = status, corrected_value
    ctx.put_model("validated", val, doc_id=doc_id)
    wh.query("update review_task set decision = ?, corrected_value = ? where task_id = ?",
             [status.value, None if corrected_value is None else json.dumps(corrected_value), task_id])
    if corrections:  # the feedback loop: every correction becomes a golden-set candidate
        dest = Path(ctx.cfg["registry"]["path"]) / "doc_types" / corrections[0]["doc_type"] / "golden"
        dest.mkdir(parents=True, exist_ok=True)
        with open(dest / "corrections.jsonl", "a") as fh:
            for c in corrections:
                fh.write(json.dumps(c, default=str) + "\n")
    return {"task_id": task_id, "decision": status.value, "facts_updated": len(fact_ids),
            "corrections_logged": len(corrections)}
