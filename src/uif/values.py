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
    if not re.search(r"\d", s):  # spoken amount
        nums = spoken_numbers(s)
        return nums[0] if nums else None
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
    if not re.search(r"\d", str(raw)):
        nums = spoken_numbers(str(raw))
        return int(nums[0]) if nums else None
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
    return spoken_date(s)


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


# ----------------------------------------------------------------------------- spoken numbers
# Call transcripts say "one hundred eighty five thousand dollars" and "October fifth, two thousand
# twenty six"; these helpers let normalizers and the validator read them.

_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                       "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000}
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
             "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
             "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
             "twentieth": 20, "thirtieth": 30}
_MONTHS = {m: i + 1 for i, m in enumerate("january february march april may june july august september october "
                                           "november december".split())}
NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_SCALES)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower().replace("-", " "))


def _parse_run(words: list[str]) -> float | None:
    """'one hundred eighty five thousand' -> 185000; 'two point eight' -> 2.8."""
    if "point" in words:
        i = words.index("point")
        whole = _parse_run(words[:i]) if words[:i] else 0
        digits = "".join(str(_UNITS[w]) for w in words[i + 1:] if w in _UNITS and _UNITS[w] < 10)
        return None if whole is None or not digits else float(f"{int(whole)}.{digits}")
    total = current = 0
    seen = False
    for w in words:
        if w == "and":
            continue
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = (current or 1) * 100
        elif w in ("thousand", "million"):
            total += (current or 1) * _SCALES[w]
            current = 0
        elif re.fullmatch(r"\d+(?:\.\d+)?", w):
            current += float(w)
        else:
            return None
        seen = True
    return float(total + current) if seen else None


def spoken_numbers(text: str) -> list[float]:
    """Every number a sentence says, in words or digits, with 'X dollars and Y cents' combined."""
    toks, out, i = _tokens(text), [], 0
    while i < len(toks):
        if toks[i] in NUMBER_WORDS or re.fullmatch(r"\d+(?:\.\d+)?", toks[i]):
            j = i
            while j < len(toks) and (toks[j] in NUMBER_WORDS or toks[j] in ("and", "point")
                                     or re.fullmatch(r"\d+(?:\.\d+)?", toks[j])):
                if toks[j] == "and" and (j + 1 >= len(toks) or toks[j + 1] not in NUMBER_WORDS):
                    break
                j += 1
            run = toks[i:j]
            while run and run[-1] in ("and", "point"):
                run.pop()
            val = _parse_run(run)
            if val is not None:
                rest = toks[j:j + 4]
                if rest[:1] == ["dollars"] and rest[1:2] == ["and"]:
                    k = j + 2
                    m = k
                    while m < len(toks) and toks[m] in NUMBER_WORDS:
                        m += 1
                    cents = _parse_run(toks[k:m])
                    if cents is not None and toks[m:m + 1] == ["cents"]:
                        out.append(round(val + cents / 100, 2))
                        i = m + 1
                        continue
                out.append(val)
            i = max(j, i + 1)
        else:
            i += 1
    return out


def spoken_date(text: str) -> str | None:
    """'October fifth, two thousand twenty six' / 'August 12 2026' -> ISO date."""
    toks = _tokens(text)
    for i, t in enumerate(toks):
        if t in _MONTHS and i + 1 < len(toks):
            day_tok = toks[i + 1]
            day, k = (_ORDINALS.get(day_tok), i + 2) if day_tok in _ORDINALS else (None, i + 1)
            if day is None and i + 2 < len(toks) and toks[i + 1] in _TENS and toks[i + 2] in _ORDINALS:
                day, k = _TENS[toks[i + 1]] + _ORDINALS[toks[i + 2]], i + 3
            if day is None and day_tok.isdigit():
                day, k = int(day_tok), i + 2
            if day is None:
                continue
            year_words = toks[k:k + 5]
            if year_words[:1] and year_words[0].isdigit() and len(year_words[0]) == 4:
                year = int(year_words[0])
            elif year_words[:2] == ["twenty", "twenty"]:
                tail = _parse_run(year_words[2:3]) or 0
                year = 2020 + int(tail)
            else:
                run = []
                for w in year_words:
                    if w in NUMBER_WORDS or w == "and":
                        run.append(w)
                    else:
                        break
                y = _parse_run(run) if run else None
                year = int(y) if y and 1990 < y < 2100 else None
            if year:
                try:
                    return dt.date(year, _MONTHS[t], day).isoformat()
                except ValueError:
                    return None
    return None


_DIGIT_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                "six": "6", "seven": "7", "eight": "8", "nine": "9"}


def spoken_digits_to_numerals(text: str) -> str:
    """Runs of two or more single-digit words become digits, keeping the pauses between groups, so
    'four one one one, one one one one' -> '4111 1111' and the guard can see card and phone numbers."""
    def repl(m: re.Match) -> str:
        words = re.findall(r"[A-Za-z]+", m.group(0))
        return "".join(_DIGIT_WORDS[w.lower()] for w in words)

    group = r"\b(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)(?:[ -](?:zero|oh|one|two|three|four|five|six|seven|eight|nine))+\b"
    text = re.sub(group, repl, text, flags=re.I)
    # "4111, 1111, 1111" -> "4111 1111 1111": pauses become the spaces that card/phone patterns expect
    return re.sub(r"(?<=\d),\s+(?=\d)", " ", text)
