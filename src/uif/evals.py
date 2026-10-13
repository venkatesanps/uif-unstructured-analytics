"""Golden-set evaluation and CI gates (design doc: Testing strategy).

Metrics
  classification_accuracy  correct doc type / documents
  field_f1 / required_f1   micro F1 over normalized values (all fields / required fields)
  grounding_rate           facts whose quote is on the cited page
  pii_leakage              planted raw identifiers found anywhere outside raw/ and restricted/
  entity_accuracy          merchant link matches the label (incl. correctly unresolved)
  review_rate              facts routed to humans
  adversarial_pass         injected docs still extract the true values"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from uif.context import Context
from uif.contracts import Classification, EntityLink, Validated
from uif.runner import process_path
from uif.values import normalize, squash

GATES = {
    "pii_leakage": ("==", 0),
    "grounding_rate": (">=", 0.99),
    "classification_accuracy": (">=", 0.95),
    "required_f1": (">=", 0.90),
}


def _same(data_type: str, pred: Any, exp: Any) -> bool:
    if pred is None or exp is None:
        return pred is None and exp is None
    if data_type in ("money", "percent"):
        return abs(float(pred) - float(exp)) < 0.01
    if data_type == "integer":
        return int(pred) == int(exp)
    if data_type == "string_list":
        return set(pred) == {str(e).lower() for e in exp}
    if data_type == "date_range":
        return pred == exp
    a, b = squash(str(pred)), squash(str(normalize(data_type, exp)))
    return a == b or (a.replace(" ", "").isdigit() and a.replace(" ", "") == b.replace(" ", ""))


def _f1(tp: int, fp: int, fn: int) -> float:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return round(2 * p * r / (p + r), 4) if p + r else 0.0


def _leak_scan(ctx: Context, raw_ids: list[str]) -> list[str]:
    if not raw_ids:
        return []
    needles = {r.replace(" ", "").replace("-", "") for r in raw_ids} | set(raw_ids)
    hits = []
    for key in ctx.store.list(""):
        if key.startswith(("raw/", "restricted/")):
            continue
        blob = ctx.store.get_bytes(key).decode("utf-8", "ignore")
        flat = blob.replace(" ", "").replace("-", "")
        if any(n in blob or n in flat for n in needles):
            hits.append(key)
    wh = ctx.providers.warehouse
    if hasattr(wh, "query"):
        for table, col in [("doc_chunk", "text_tokenized"), ("extracted_fact", "evidence_quote"),
                           ("extracted_fact", "CAST(value_raw AS VARCHAR)")]:
            for (text,) in wh.query(f"select {col} from {table}"):
                t = (text or "")
                if any(n in t or n in t.replace(" ", "").replace("-", "") for n in needles):
                    hits.append(f"warehouse:{table}")
    return sorted(set(hits))


def evaluate(ctx: Context, path: str | Path, run_pipeline: bool = True) -> dict[str, Any]:
    path = Path(path)
    labels = [json.loads(p.read_text()) for p in sorted((path / "labels").glob("*.json"))]
    if run_pipeline:
        for group in sorted({l["source_group"] for l in labels}):
            process_path(ctx, path / group, group, "golden", force=True)

    cls_ok = 0
    ent_ok = 0
    counts = defaultdict(lambda: [0, 0, 0])  # (doc_type, field) -> tp, fp, fn
    facts_total = grounded = reviewed = 0
    adversarial = []
    per_doc = []
    all_raw = []
    for lab in labels:
        doc_id = hashlib.sha256((path / lab["file"]).read_bytes()).hexdigest()[:20]
        all_raw += lab.get("raw_identifiers", [])
        try:
            cls = ctx.get_model("classification", Classification, doc_id=doc_id)
            val = ctx.get_model("validated", Validated, doc_id=doc_id)
            link = ctx.get_model("entity", EntityLink, doc_id=doc_id)
        except FileNotFoundError:
            per_doc.append({"file": lab["file"], "error": "not processed"})
            counts[(lab["doc_type"], "*missing_doc*")][2] += 1
            continue
        cls_ok += cls.doc_type == lab["doc_type"]
        ent_ok += link.merchant_id == lab.get("merchant_id")
        preds = {f.field_path: f for f in val.facts}
        wrong = []
        if lab["doc_type"] in ctx.registry:
            dt = ctx.registry.get(lab["doc_type"])
            for name in dt.fields:
                exp = lab["fields"].get(name)
                exp_n = normalize(dt.field_type(name), exp) if exp is not None else None
                if exp_n == []:
                    exp_n = None
                pred = preds[name].value_norm if name in preds else None
                c = counts[(dt.name, name)]
                if exp_n is None and pred is None:
                    continue
                if pred is not None and exp_n is not None and _same(dt.field_type(name), pred, exp_n):
                    c[0] += 1
                else:
                    if pred is not None:
                        c[1] += 1
                    if exp_n is not None:
                        c[2] += 1
                    wrong.append({"field": name, "expected": exp_n, "got": pred})
        for f in val.facts:
            facts_total += 1
            grounded += "not_grounded" not in f.review_reasons
            reviewed += f.review_status == "needs_review"
        if "adversarial" in lab.get("flags", []):
            adversarial.append(not wrong)
        per_doc.append({"file": lab["file"], "doc_type": cls.doc_type, "wrong": wrong,
                        "review_tasks": [t.reason for t in val.review_tasks]})

    def micro(keys):
        tp = sum(counts[k][0] for k in keys)
        fp = sum(counts[k][1] for k in keys)
        fn = sum(counts[k][2] for k in keys)
        return _f1(tp, fp, fn)

    required = [(dt, f) for (dt, f) in counts if dt in ctx.registry and f in ctx.registry.get(dt).required]
    by_field = {f"{dt}.{f}": _f1(*v) for (dt, f), v in sorted(counts.items())}
    leaks = _leak_scan(ctx, all_raw)
    n = len(labels)
    return {
        "llm": ctx.providers.llm.model_id,
        "documents": n,
        "classification_accuracy": round(cls_ok / n, 4) if n else 0.0,
        "field_f1": micro(list(counts)),
        "required_f1": micro(required),
        "grounding_rate": round(grounded / facts_total, 4) if facts_total else 1.0,
        "pii_leakage": len(leaks),
        "pii_leak_locations": leaks,
        "entity_accuracy": round(ent_ok / n, 4) if n else 0.0,
        "review_rate": round(reviewed / facts_total, 4) if facts_total else 0.0,
        "adversarial_pass": all(adversarial) if adversarial else None,
        "by_field_f1": by_field,
        "documents_detail": per_doc,
    }


def gate(report: dict[str, Any], gates: dict = GATES) -> list[str]:
    failures = []
    for metric, (op, target) in gates.items():
        v = report[metric]
        ok = v == target if op == "==" else v >= target
        if not ok:
            failures.append(f"{metric}={v} (need {op} {target})")
    if report.get("adversarial_pass") is False:
        failures.append("adversarial_pass=False")
    return failures
