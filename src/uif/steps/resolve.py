"""Step 6: link the document to a merchant. Deterministic first; fuzzy name second.
(An LLM adjudicator for near-ties slots in here in Phase 1.)"""

from __future__ import annotations

import difflib
import re

from uif.context import Context
from uif.contracts import EntityLink, Extraction, StepResult

_SUFFIX = re.compile(r"\b(llc|inc|corp|corporation|co|ltd|lp|llp|pllc|company)\b\.?", re.I)
NAME_FIELDS = ("merchant_legal_name", "merchant_name", "dba_name")


def norm_name(s: str) -> str:
    s = s.lower().replace(".", "").replace("&", " and ")  # "L.L.C." -> "llc", "Maple & Main" == "Maple and Main"
    s = _SUFFIX.sub("", s)
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def resolve(master: list[dict[str, str]], mid: str | None, names: list[str], min_ratio: float = 0.88):
    if mid:
        digits = re.sub(r"\D", "", str(mid))
        for row in master:
            if re.sub(r"\D", "", row["mid"]) == digits:
                return row, "mid_exact", 1.0
    best, best_score = None, 0.0
    for name in filter(None, names):
        n = norm_name(name)
        for row in master:
            for cand in (row.get("legal_name", ""), row.get("dba", "")):
                score = difflib.SequenceMatcher(None, n, norm_name(cand)).ratio()
                if score > best_score:
                    best, best_score = row, score
    if best and best_score >= min_ratio:
        return best, "name_fuzzy", round(best_score, 3)
    return None, "none", round(best_score, 3)


def run(ctx: Context, doc_id: str) -> StepResult:
    ext = ctx.get_model("extraction", Extraction, doc_id=doc_id)
    mid = ext.fields.get("mid").value if "mid" in ext.fields else None
    names = [ext.fields[f].value for f in NAME_FIELDS if f in ext.fields]
    row, method, score = resolve(ctx.master, mid, names)
    link = EntityLink(doc_id=doc_id, merchant_id=row["merchant_id"] if row else None,
                      mid=row["mid"] if row else None, legal_name=row["legal_name"] if row else None,
                      match_method=method, match_score=score)
    key = ctx.put_model("entity", link, doc_id=doc_id)
    return StepResult(doc_id=doc_id, step="resolve", ok=True, output_key=key,
                      detail=f"{link.merchant_id or 'unresolved'} via {method} ({score})")
