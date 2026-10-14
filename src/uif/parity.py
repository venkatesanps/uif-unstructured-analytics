"""Parity: does the extractor you test with locally (Claude Code / Copilot via handoff) behave
like the one production uses (Bedrock)? Both answer the SAME requests (same tokenized text,
prompts and schema); this module diffs their answers field by field and, given golden labels,
scores each against ground truth by replaying the answers through the real pipeline.

The report is Gate C evidence: high agreement plus both sides passing the gates means local results
are a fair predictor of production; disagreements show exactly where they diverge."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from uif.registry import Registry
from uif.values import normalize, squash

PARITY_GATES = {"required_agreement": 0.95}


def load_dir(path: str | Path) -> dict[str, dict[str, Any]]:
    out = {}
    for f in sorted(Path(path).glob("*.json")):
        d = json.loads(f.read_text())
        out[d.get("request_id", f.stem)] = d
    return out


def _same(data_type: str, a: Any, b: Any) -> bool:
    if a is None or b is None or a == [] or b == []:
        return (a in (None, [])) and (b in (None, []))
    if data_type in ("money", "percent"):
        return abs(float(a) - float(b)) < 0.01
    if data_type == "integer":
        return int(a) == int(b)
    if data_type == "string_list":
        return set(a) == set(b)
    if data_type in ("date_range",):
        return a == b
    sa, sb = squash(str(a)), squash(str(b))
    return sa == sb or sa.replace(" ", "") == sb.replace(" ", "")


def diff(requests: dict[str, dict], a: dict[str, dict], b: dict[str, dict], registry: Registry) -> dict[str, Any]:
    rows = defaultdict(lambda: [0, 0])  # doc_type.field -> [agree, total]
    required = set()
    disagreements, missing = [], {"a": [], "b": []}
    cls_agree = cls_total = 0
    for rid, req in sorted(requests.items()):
        if rid not in a:
            missing["a"].append(rid)
        if rid not in b:
            missing["b"].append(rid)
        if rid not in a or rid not in b:
            continue
        if req["kind"] == "classify":
            cls_total += 1
            if a[rid].get("doc_type") == b[rid].get("doc_type"):
                cls_agree += 1
            else:
                disagreements.append({"request_id": rid, "doc_type": "(classify)", "field": "doc_type",
                                      "a": {"value": a[rid].get("doc_type")}, "b": {"value": b[rid].get("doc_type")}})
            continue
        dt = registry.get(req["doc_type"]) if req["doc_type"] in registry else None
        for name in req["response_schema"]["properties"]:
            ftype = dt.field_type(name) if dt else "string"
            fa = (a[rid].get("fields") or {}).get(name) or {}
            fb = (b[rid].get("fields") or {}).get(name) or {}
            va, vb = normalize(ftype, fa.get("value")), normalize(ftype, fb.get("value"))
            key = f"{req['doc_type']}.{name}"
            if dt and name in dt.required:
                required.add(key)
            rows[key][1] += 1
            if _same(ftype, va, vb):
                rows[key][0] += 1
            else:
                disagreements.append({
                    "request_id": rid, "doc_type": req["doc_type"], "field": name,
                    "a": {"value": va, "quote": fa.get("quote"), "confidence": fa.get("confidence")},
                    "b": {"value": vb, "quote": fb.get("quote"), "confidence": fb.get("confidence")}})

    def rate(keys):
        agree = sum(rows[k][0] for k in keys)
        total = sum(rows[k][1] for k in keys)
        return round(agree / total, 4) if total else 1.0

    titles = {}
    for rid, req in requests.items():
        body = req.get("user_prompt", "")
        first = body.split("[page 1]", 1)[-1].strip().splitlines()
        titles[rid] = f"{req.get('doc_type', req['kind'])}: " + (first[0][:70] if first else "")
    return {
        "titles": titles,
        "requests": len(requests),
        "compared": len(requests) - len(set(missing["a"]) | set(missing["b"])),
        "agreement": rate(list(rows)),
        "required_agreement": rate([k for k in rows if k in required]),
        "classification_agreement": round(cls_agree / cls_total, 4) if cls_total else 1.0,
        "by_field": {k: {"agree": v[0], "total": v[1], "rate": round(v[0] / v[1], 4)} for k, v in sorted(rows.items())},
        "disagreements": disagreements,
        "missing": missing,
    }


def gate(report: dict[str, Any]) -> list[str]:
    fails = [f"{k}={report[k]} (need >= {v})" for k, v in PARITY_GATES.items() if report[k] < v]
    if report["missing"]["a"] or report["missing"]["b"]:
        fails.append(f"unanswered requests: a={len(report['missing']['a'])}, b={len(report['missing']['b'])}")
    return fails


def replay_eval(answers_dir: str | Path, golden: str | Path) -> dict[str, Any]:
    """Score a set of answers against golden labels by replaying them through the real pipeline
    (validator, resolver, publish) in a throwaway store."""
    from uif.context import Context
    from uif.evals import evaluate

    tmp = Path(tempfile.mkdtemp(prefix="uif-replay-"))
    try:
        resp = tmp / "store" / "handoff" / "responses"
        resp.mkdir(parents=True)
        for f in Path(answers_dir).glob("*.json"):
            shutil.copy(f, resp / f.name)
        ctx = Context.from_config("local", {"store.root": str(tmp / "store"),
                                            "warehouse.path": str(tmp / "uif.duckdb"), "llm.kind": "handoff"})
        report = evaluate(ctx, golden, run_pipeline=True)
        ctx.providers.warehouse.close()
        pending = sum(1 for d in report["documents_detail"] if d.get("error"))
        report["unanswered_documents"] = pending
        return report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_HEADLINE = ["classification_accuracy", "required_f1", "field_f1", "grounding_rate", "pii_leakage",
             "entity_accuracy", "review_rate", "adversarial_pass"]


def render_markdown(report: dict[str, Any], names: tuple[str, str], evals: tuple[dict, dict] | None = None,
                    show_quotes: bool = True, max_rows: int = 60) -> str:
    a, b = names
    fails = gate(report)
    lines = [f"# Extractor parity: {a} vs {b}", "",
             f"Verdict: **{'PASS' if not fails else 'FAIL'}**" + ("" if not fails else " — " + "; ".join(fails)), "",
             f"{report['compared']} of {report['requests']} requests compared. Field agreement "
             f"{report['agreement']:.1%}, required fields {report['required_agreement']:.1%}, "
             f"classification {report['classification_agreement']:.1%}.", ""]
    if evals:
        from uif.evals import gate as eval_gate

        ea, eb = evals
        lines += ["## Against golden labels", "", f"| Metric | {a} | {b} |", "| --- | --- | --- |"]
        lines += [f"| {m} | {ea.get(m)} | {eb.get(m)} |" for m in _HEADLINE]
        lines += [f"| gates | {'pass' if not eval_gate(ea) else 'FAIL'} | {'pass' if not eval_gate(eb) else 'FAIL'} |", ""]
    weak = {k: v for k, v in report["by_field"].items() if v["rate"] < 1}
    lines += ["## Fields where they differ", ""]
    if weak:
        lines += ["| Field | Agree | Rate |", "| --- | --- | --- |"]
        lines += [f"| {k} | {v['agree']}/{v['total']} | {v['rate']:.0%} |" for k, v in sorted(weak.items(), key=lambda x: x[1]["rate"])]
    else:
        lines.append("None: every field agreed.")
    lines.append("")
    if report["disagreements"]:
        lines += ["## Disagreements", ""]
        hdr = f"| Request | Field | {a} | {b} |" if not show_quotes else f"| Request | Field | {a} | {b} | {a} quote | {b} quote |"
        lines += [hdr, "| --- " * (hdr.count("|") - 1) + "|"]
        for d in report["disagreements"][:max_rows]:
            cell = lambda v: str(v).replace("|", "\\|").replace("\n", " ")
            row = (f"| {d['request_id']} | {d['doc_type']}.{d['field']} | {cell(json.dumps(d['a'].get('value')))} "
                   f"| {cell(json.dumps(d['b'].get('value')))} |")
            if show_quotes:
                qa, qb = (d["a"].get("quote") or "")[:80], (d["b"].get("quote") or "")[:80]
                row += f" {cell(qa)} | {cell(qb)} |"
            lines.append(row.replace("\n", " "))
        if len(report["disagreements"]) > max_rows:
            lines.append(f"\n…and {len(report['disagreements']) - max_rows} more (see the JSON report).")
        legend = report.get("titles", {})
        ids = sorted({d["request_id"] for d in report["disagreements"]})
        if legend and ids:
            lines += ["", "Requests:", ""] + [f"- `{i}`: {legend.get(i, '')}" for i in ids]
    return "\n".join(lines) + "\n"
