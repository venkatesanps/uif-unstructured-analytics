"""Step 7: turn raw extractions into facts and decide what a human must see.

A fact goes to review when any of these hold:
  - not_grounded:   the quote is not on the cited page (model invented evidence)
  - value_not_in_quote: the number does not appear in its own quote
  - unparseable:    the value cannot be normalized to its declared type
  - low_confidence: confidence below the field's review_below
  - rule:<id>:      a schema rule failed (rule failures flag every field they name)
Document-level tasks: unknown doc type, unresolved merchant, missing required field."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from uif.context import Context
from uif.contracts import (
    Classification,
    EntityLink,
    Extraction,
    Fact,
    GuardedDoc,
    ReviewStatus,
    ReviewTask,
    StepResult,
    Validated,
)
from uif.values import normalize, spoken_numbers, squash

_NUM = re.compile(r"\(?-?\$?\d[\d,]*(?:\.\d+)?\)?")


def _id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def grounded(quote: str | None, page_text: str | None) -> bool:
    return bool(quote) and bool(page_text) and squash(quote) in squash(page_text)


def value_in_quote(data_type: str, norm: Any, quote: str, spec: dict | None = None) -> bool:
    vocab = (spec or {}).get("vocabulary")
    if data_type == "enum" and vocab:  # category value: the quote must carry one of its phrases
        return any(squash(w) in squash(quote) for w in vocab.get(str(norm), []))
    if data_type in ("money", "integer", "percent"):
        nums = []
        for tok in _NUM.findall(quote):
            v = normalize("money", tok)
            if v is not None:
                nums.append(abs(v))
        nums += [abs(v) for v in spoken_numbers(quote)]  # transcripts: "two point eight percent"
        return norm is not None and any(abs(abs(float(norm)) - n) < 0.005 for n in nums)
    if data_type in ("string", "enum"):
        if squash(str(norm)) in squash(quote):
            return True
        # spoken or reformatted identifiers: "C B 2026 814273" supports CB-2026-814273,
        # "Blue Harbor Coffee L L C" supports Blue Harbor Coffee LLC
        alnum = lambda t: re.sub(r"[^a-z0-9]", "", str(t).lower())
        if alnum(norm) and alnum(norm) in alnum(quote):
            return True
        # a numeric code said aloud: "reason code thirteen point one" supports 13.1
        try:
            return any(abs(float(norm) - v) < 1e-9 for v in spoken_numbers(quote))
        except ValueError:
            return False
    return True  # dates, ranges and lists are format-shifted; grounding of the quote is the check


def check_rule(rule: dict[str, Any], values: dict[str, Any], reference=None) -> bool | None:
    """None = not evaluable (an operand is missing). `reference(name)` returns a lookup table
    (list of dicts) for the in_ref / ref_pair checks."""
    op = rule["check"]
    if op in ("in_ref", "ref_pair"):
        if reference is None:
            return None
        table = reference(rule["ref"])
        left = values.get(rule["left"])
        if left is None:
            return None
        if op == "in_ref":
            return str(left).lower() in {r[rule["ref_column"]].lower() for r in table}
        right = values.get(rule["right"])
        if right is None:
            return None
        lc, rc = rule["ref_columns"]
        return (str(left).lower(), str(right).lower()) in {(r[lc].lower(), r[rc].lower()) for r in table}
    left = values.get(rule["left"])
    right = values.get(rule["right"]) if "right" in rule else rule.get("value")
    if left is None or right is None:
        return None
    if op == "lte":
        return left <= right
    if op == "gte":
        return left >= right
    if op == "between":
        lo, hi = rule["range"]
        return lo <= left <= hi
    if op == "in":
        return left in rule["values"]
    raise ValueError(f"unknown rule check {op}")


def run(ctx: Context, doc_id: str) -> StepResult:
    cls = ctx.get_model("classification", Classification, doc_id=doc_id)
    ext = ctx.get_model("extraction", Extraction, doc_id=doc_id)
    link = ctx.get_model("entity", EntityLink, doc_id=doc_id)
    guarded_doc = ctx.get_model("guarded", GuardedDoc, doc_id=doc_id)
    pages = {p.page: p.text for p in guarded_doc.pages}
    tasks: list[ReviewTask] = []

    if cls.doc_type not in ctx.registry:
        tasks.append(ReviewTask(task_id=_id(doc_id, "unknown"), doc_id=doc_id, fact_ids=[],
                                reason="unknown_doc_type"))
        out = Validated(doc_id=doc_id, facts=[], review_tasks=tasks)
        key = ctx.put_model("validated", out, doc_id=doc_id)
        return StepResult(doc_id=doc_id, step="validate", ok=True, output_key=key, detail="unknown doc type -> review")

    dt = ctx.registry.get(ext.doc_type)
    reasons: dict[str, list[str]] = {name: [] for name in dt.fields}
    norm_values: dict[str, Any] = {}

    for name, fv in ext.fields.items():
        if name not in dt.fields or fv.value in (None, [], ""):
            continue
        ftype = dt.field_type(name)
        norm = normalize(ftype, fv.value)
        norm_values[name] = norm
        if norm in (None, []) and ftype != "string":
            reasons[name].append("unparseable")
        if not grounded(fv.quote, pages.get(fv.page or -1)):
            reasons[name].append("not_grounded")
        elif norm is not None and not value_in_quote(ftype, norm, fv.quote or "", dt.fields[name]):
            reasons[name].append("value_not_in_quote")
        vocab = dt.fields[name].get("vocabulary")
        if ftype == "string_list" and vocab and norm:
            # one quote can't vouch for a whole list: every item needs its own phrase in the document
            dehyphen = lambda t: squash(t.replace("-", " "))  # "small dollar" == "small-dollar" (transcripts)
            doc_text = dehyphen(" ".join(pages.values()))
            known = {k.lower(): v for k, v in vocab.items()}
            for item in norm:
                if item not in known:
                    reasons[name].append(f"item_not_in_vocabulary:{item}")
                elif not any(dehyphen(w) in doc_text for w in known[item]):
                    reasons[name].append(f"item_not_in_document:{item}")
        if fv.confidence < dt.review_below(name, ctx.default_review_below):
            reasons[name].append("low_confidence")
        if ftype == "enum" and dt.fields[name].get("values") and norm not in dt.fields[name]["values"]:
            reasons[name].append("enum_out_of_range")

    for flag in guarded_doc.quality_flags:  # e.g. low-accuracy transcript: nothing from it is auto-accepted
        for name in reasons:
            if name in norm_values:
                reasons[name].append(f"source:{flag}")

    rule_failures = []
    for rule in dt.rules:
        if check_rule(rule, norm_values, ctx.reference) is False:
            rule_failures.append(rule["id"])
            for f in (rule.get("left"), rule.get("right")):
                if f in reasons:
                    reasons[f].append(f"rule:{rule['id']}")

    missing = [f for f in dt.required if f not in norm_values]
    facts = []
    for name, fv in ext.fields.items():
        if name not in norm_values:
            continue
        status = ReviewStatus.needs_review if reasons[name] else ReviewStatus.auto_accepted
        facts.append(Fact(
            fact_id=_id(doc_id, dt.name, name), doc_id=doc_id, schema_name=dt.name, schema_version=dt.version,
            field_path=name, value_raw=fv.value, value_norm=norm_values[name], data_type=dt.field_type(name),
            confidence=fv.confidence, evidence_page=fv.page, evidence_quote=fv.quote, run_id=ext.run.run_id,
            review_status=status, review_reasons=reasons[name],
        ))
        if reasons[name]:
            tasks.append(ReviewTask(task_id=_id(doc_id, "fact", name), doc_id=doc_id,
                                    fact_ids=[facts[-1].fact_id], reason=";".join(reasons[name])))
    for flag in guarded_doc.quality_flags:
        tasks.append(ReviewTask(task_id=_id(doc_id, "quality", flag), doc_id=doc_id, fact_ids=[],
                                reason=f"source_quality:{flag}"))
    if missing:
        tasks.append(ReviewTask(task_id=_id(doc_id, "missing"), doc_id=doc_id, fact_ids=[],
                                reason="missing_required:" + ",".join(missing)))
    if link.merchant_id is None and any(f in dt.fields for f in ("mid", "merchant_legal_name", "merchant_name")):
        tasks.append(ReviewTask(task_id=_id(doc_id, "entity"), doc_id=doc_id, fact_ids=[],
                                reason="unresolved_merchant"))

    out = Validated(doc_id=doc_id, facts=facts, review_tasks=tasks, rule_failures=rule_failures)
    key = ctx.put_model("validated", out, doc_id=doc_id)
    auto = sum(1 for f in facts if f.review_status == ReviewStatus.auto_accepted)
    return StepResult(doc_id=doc_id, step="validate", ok=True, output_key=key,
                      detail=f"{auto}/{len(facts)} auto-accepted, {len(tasks)} review task(s)")
