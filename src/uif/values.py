"""Value normalizers shared by extractors and the validator."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

_MONEY = re.compile(r"[-+]?\$?\s*\(?[\d,]+(?:\.\d+)?\)?")
_DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%b %d %Y"]


def to_money(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    neg = s.startswith("(") and s.endswith(")") or s.startswith("-")
    digits = re.sub(r"[^\d.]", "", s)
    if not digits or digits == ".":
        return None
    val = float(digits)
    return -val if neg else val


def to_int(raw: Any) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    digits = re.sub(r"[^\d-]", "", str(raw))
    return int(digits) if digits not in ("", "-") else None


def to_date(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def to_date_range(raw: Any) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, dict) and "start" in raw:
        return {"start": to_date(raw["start"]), "end": to_date(raw.get("end"))}
    parts = re.split(r"\s+(?:to|through|-|–)\s+", str(raw).strip())
    if len(parts) != 2:
        return None
    start, end = to_date(parts[0]), to_date(parts[1])
    return {"start": start, "end": end} if start and end else None


def to_percent(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    m = re.search(r"-?\d+(?:\.\d+)?", str(raw))
    return float(m.group()) if m else None


def normalize(data_type: str, raw: Any) -> Any:
    fn = {
        "money": to_money,
        "integer": to_int,
        "date": to_date,
        "date_range": to_date_range,
        "percent": to_percent,
    }.get(data_type)
    if fn:
        return fn(raw)
    if data_type == "string":
        return None if raw is None else " ".join(str(raw).split())
    if data_type == "string_list":
        if raw is None:
            return []
        items = raw if isinstance(raw, list) else re.split(r"[;,]", str(raw))
        return sorted({" ".join(str(i).split()).lower() for i in items if str(i).strip()})
    if data_type == "enum":
        return None if raw is None else str(raw).strip().lower()
    return raw


def squash(text: str) -> str:
    """Whitespace- and case-insensitive form used for grounding checks."""
    return re.sub(r"\s+", " ", text or "").strip().lower()
