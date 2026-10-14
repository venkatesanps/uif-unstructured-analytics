"""Local adapters: filesystem store, pdfplumber/tesseract OCR, regex+Luhn guard,
an offline rules extractor, an Ollama extractor, and DuckDB."""

from __future__ import annotations

import email
import email.policy
import hashlib
import html
import json
import re
import shutil
import subprocess
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import requests

from uif.contracts import GuardFinding, Page
from uif.providers.base import ClassifyOutput, ExtractionOutput, LLMUsage
from uif.providers.llm_common import (
    SYSTEM_PROMPT,
    classify_prompt,
    coerce_fields,
    parse_json,
    response_schema,
    user_prompt,
)
from uif.registry import DocType

# --------------------------------------------------------------------------- store


class LocalStore:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError(f"key escapes store root: {key}")
        return p

    def put_bytes(self, key: str, data: bytes) -> str:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return self.uri(key)

    def get_bytes(self, key: str) -> bytes:
        return self._p(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._p(key).exists()

    def list(self, prefix: str) -> list[str]:
        base = self._p(prefix) if prefix else self.root
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())

    def uri(self, key: str) -> str:
        return f"file://{self._p(key)}"

    def delete(self, key: str) -> None:
        self._p(key).unlink(missing_ok=True)


# --------------------------------------------------------------------------- OCR / normalize


def _strip_html(text: str) -> str:
    """Visible text only, one block per line; a table row <th>Label</th><td>Value</td> reads as
    "Label: value" so labelled fields survive the conversion."""
    text = re.sub(r"(?is)<(script|style|head|nav)\b.*?</\1>", " ", text)
    text = re.sub(r"(?i)</th>", ": ", text)
    text = re.sub(r"(?i)</td>", " | ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</li>|</header>|</footer>|</aside>|</article>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines = (re.sub(r"[ \t]+", " ", line).strip().rstrip("|").strip() for line in html.unescape(text).splitlines())
    return "\n".join(line for line in lines if line)


def _split_pages(text: str) -> list[Page]:
    chunks = text.split("\f") if "\f" in text else [text]
    return [Page(page=i + 1, text=c.strip()) for i, c in enumerate(chunks) if c.strip()]


def email_pages(data: bytes, attachment_to_pages) -> tuple[list[Page], str]:
    """Email body becomes page 1; each attachment is normalized with `attachment_to_pages`
    (local OCR or Textract) and appended, with a header naming the attachment so evidence
    quotes and reviewers can tell which file a page came from."""
    msg = email.message_from_bytes(data, policy=email.policy.default)
    header = "\n".join(f"{h}: {msg[h]}" for h in ("From", "To", "Date", "Subject") if msg[h])
    body = msg.get_body(preferencelist=("plain", "html"))
    content = body.get_content() if body else ""
    if body is not None and body.get_content_type() == "text/html":
        content = _strip_html(content)
    pages = [Page(page=1, text=f"{header}\n\n{content}")]
    methods = {"email"}
    for part in msg.iter_attachments():
        ctype = part.get_content_type()
        payload = part.get_content()
        name = part.get_filename()
        if isinstance(payload, str):
            payload = payload.encode()
        elif not isinstance(payload, (bytes, bytearray)):  # nested message/rfc822 (forwarded email)
            name = name or f"forwarded email: {payload['Subject'] or 'no subject'}"
            payload, ctype = bytes(payload), "message/rfc822"
        name = name or f"attachment-{len(pages)}"
        try:
            sub, method = attachment_to_pages(bytes(payload), ctype, name)
        except NotImplementedError:
            pages.append(Page(page=len(pages) + 1, text=f"[attachment: {name}] unsupported type {ctype}; not read"))
            continue
        methods.add(method)
        for p in sub:
            pages.append(Page(page=len(pages) + 1, text=f"[attachment: {name}, page {p.page}]\n{p.text}"))
    return pages, "+".join(sorted(methods))


class LocalOCR:
    """Native PDFs via pdfplumber; scans and images via the tesseract CLI if installed."""

    def __init__(self, tesseract_cmd: str | None = None, transcriber=None):
        from uif.providers.formats import WhisperCppTranscriber

        self.tesseract = tesseract_cmd or shutil.which("tesseract")
        self.transcriber = transcriber or WhisperCppTranscriber()

    def _tesseract_image(self, image_path: str) -> str:
        if not self.tesseract:
            raise RuntimeError("tesseract not installed; cannot OCR scanned pages")
        out = subprocess.run([self.tesseract, image_path, "stdout"], capture_output=True, text=True, check=True)
        return out.stdout

    def _pdf(self, data: bytes) -> tuple[list[Page], str]:
        import pdfplumber

        pages, method = [], "pdfplumber"
        with pdfplumber.open(BytesIO(data)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                if len(text.strip()) < 20 and self.tesseract:  # likely a scan
                    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
                        page.to_image(resolution=300).original.save(tmp.name)
                        text = self._tesseract_image(tmp.name)
                    method = "pdfplumber+tesseract"
                pages.append(Page(page=i, text=text))
        return pages, method

    def to_pages(self, data: bytes, mime_type: str, file_name: str) -> tuple[list[Page], str]:
        if mime_type == "application/pdf":
            return self._pdf(data)
        if mime_type.startswith("image/"):
            suffix = Path(file_name).suffix or ".png"
            with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
                tmp.write(data)
                tmp.flush()
                # multi-page TIFF (fax): tesseract separates pages with form feeds
                return _split_pages(self._tesseract_image(tmp.name)), "tesseract"
        if mime_type == "message/rfc822":
            return email_pages(data, self.to_pages)
        from uif.providers import formats as fmt

        if mime_type == fmt.DOCX:
            return fmt.docx_pages(data), "docx"
        if mime_type == fmt.XLSX:
            return fmt.xlsx_pages(data), "xlsx"
        if mime_type == "text/csv":
            return fmt.csv_pages(data), "csv"
        if mime_type == "application/json":
            return fmt.json_pages(data), "json"
        if mime_type in fmt.ZIP_TYPES:
            return fmt.zip_pages(data, self.to_pages, fmt.guess_mime)
        if mime_type.startswith("audio/"):
            return fmt.audio_pages(data, file_name, self.transcriber), "transcript"
        if mime_type == "text/html":
            return _split_pages(_strip_html(data.decode("utf-8", "replace"))), "html"
        if mime_type.startswith("text/"):
            return _split_pages(data.decode("utf-8", "replace")), "text"
        raise NotImplementedError(f"no local normalizer for {mime_type}")


# --------------------------------------------------------------------------- guard

# A card number is a whole run of digits: it may not start or end inside a longer grouped run
# (USPS tracking numbers are 22 digits in groups of 4, and a 16-digit window can pass Luhn).
_PAN = re.compile(r"(?<![\d-])(?<!\d[ -])(?:\d[ -]?){12,18}\d(?![\d-])(?![ -]\d{3})")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# OCR often splits addresses ("disputes @ lakeside-example .com"); allow single spaces around @ and dots,
# but require an alphabetic TLD so "qty 2 @ 5.00" is not taken for an email.
_EMAIL = re.compile(r"\b[\w.+-]+ ?@ ?[\w-]+(?: ?\. ?[\w-]+)*? ?\. ?[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")
_BANK = re.compile(r"(?i)(?:account|acct|routing)\s*(?:number|no\.?|#)?\s*[:#]?\s*(\d{6,17})")
_NOT_A_CARD_CONTEXT = re.compile(r"(?i)(mid|merchant\s*id|merchant\s*number|tid|terminal|invoice|order|tracking)\W{0,4}$")


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def looks_like_pan(candidate: str, preceding: str = "") -> bool:
    digits = re.sub(r"\D", "", candidate)
    if not 13 <= len(digits) <= 19 or digits[0] not in "23456":
        return False
    if _NOT_A_CARD_CONTEXT.search(preceding):
        return False
    return luhn_ok(digits)


class RegexGuard:
    """Tokenizes card numbers and PII. Tokens are salted hashes, so the same value
    maps to the same token across documents (joinable) and raw values are never stored."""

    def __init__(self, token_salt: str):
        self.salt = token_salt.encode()

    def token(self, kind: str, value: str) -> str:
        norm = re.sub(r"\s|-", "", value).lower()
        return f"<{kind.upper()}_{hashlib.sha256(self.salt + norm.encode()).hexdigest()[:10]}>"

    def _sub(self, pattern, kind, text, page, findings, check=None, group=0):
        def repl(m: re.Match) -> str:
            span_text = m.group(group)
            if check and not check(span_text, text[max(0, m.start() - 24):m.start()]):
                return m.group(0)
            tok = self.token(kind, span_text)
            findings.append(GuardFinding(kind=kind, page=page, token=tok))
            return m.group(0).replace(span_text, tok)

        return pattern.sub(repl, text)

    def scan(self, pages: list[Page]) -> tuple[list[Page], list[GuardFinding]]:
        findings: list[GuardFinding] = []
        out = []
        for p in pages:
            t = p.text
            t = self._sub(_PAN, "pan", t, p.page, findings, check=looks_like_pan)
            t = self._sub(_SSN, "ssn", t, p.page, findings)
            t = self._sub(_BANK, "bank_account", t, p.page, findings, group=1)
            t = self._sub(_EMAIL, "email", t, p.page, findings)
            t = self._sub(_PHONE, "phone", t, p.page, findings)
            out.append(Page(page=p.page, text=t))
        return out, findings


# --------------------------------------------------------------------------- extractors


def _sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    rights = [i for i in (text.find(".", end), text.find("\n", end)) if i != -1]
    right = min(rights) if rights else len(text)
    return " ".join(text[left:right + 1].split())[:200]


class RulesExtractor:
    """Offline, deterministic baseline. Uses each field's `hints` (regexes with one
    capture group) and `vocabulary` (theme -> keywords). It exists so the whole
    pipeline, its tests and its evals run with no model at all, and so a model's
    gain over a dumb baseline is measurable."""

    model_id = "rules-v1"

    def extract(self, pages: list[Page], doc_type: DocType) -> ExtractionOutput:
        t0 = time.perf_counter()
        fields: dict[str, dict[str, Any]] = {}
        for name, spec in doc_type.fields.items():
            fields[name] = {"value": None, "page": None, "quote": None, "confidence": 0.0}
            if spec["type"] == "string_list" and spec.get("vocabulary"):
                found, first = [], None
                for page in pages:
                    low = page.text.lower()
                    for theme, words in spec["vocabulary"].items():
                        for w in words:
                            i = low.find(w.lower())
                            if i != -1 and theme not in found:
                                found.append(theme)
                                first = first or (page.page, _sentence_around(page.text, i, i + len(w)))
                if found:
                    fields[name] = {"value": found, "page": first[0], "quote": first[1],
                                    "confidence": spec.get("hint_confidence", 0.75)}
                continue
            if spec["type"] == "enum" and spec.get("vocabulary"):
                best = None  # earliest phrase in reading order decides the value
                for page in pages:
                    low = page.text.lower()
                    for value, words in spec["vocabulary"].items():
                        for w in words:
                            i = low.find(w.lower())
                            if i != -1 and (best is None or (page.page, i) < best[:2]):
                                best = (page.page, i, value, _sentence_around(page.text, i, i + len(w)))
                if best:
                    fields[name] = {"value": best[2], "page": best[0], "quote": best[3],
                                    "confidence": spec.get("hint_confidence", 0.8)}
                continue
            for pattern in spec.get("hints", []):
                rx = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                hit = next(((p, m) for p in pages for m in [rx.search(p.text)] if m), None)
                if hit:
                    page, m = hit
                    value = m.group(1) if m.groups() else m.group(0)
                    fields[name] = {"value": value.strip(), "page": page.page,
                                    "quote": " ".join(m.group(0).split())[:200],
                                    "confidence": spec.get("hint_confidence", 0.9)}
                    break
        ms = int((time.perf_counter() - t0) * 1000)
        return ExtractionOutput(fields=fields, usage=LLMUsage(self.model_id, latency_ms=ms))

    def classify(self, pages: list[Page], candidates: list[DocType]) -> ClassifyOutput:
        text = " ".join(p.text for p in pages).lower()
        scores = {}
        for d in candidates:
            if d.keywords:
                scores[d.name] = sum(1 for k in d.keywords if k in text) / len(d.keywords)
        best = max(scores, key=scores.get) if scores else "unknown"
        conf = scores.get(best, 0.0)
        return ClassifyOutput(doc_type=best if conf > 0 else "unknown", confidence=round(conf, 3),
                              usage=LLMUsage(self.model_id), scores=scores)


class OllamaLLM:
    """Local model via Ollama's /api/chat with a JSON-schema `format` (structured output)."""

    def __init__(self, host: str, model: str, timeout_s: int = 180):
        self.host, self.model_id, self.timeout = host.rstrip("/"), model, timeout_s

    def _chat(self, prompt: str, fmt: Any) -> tuple[Any, LLMUsage]:
        t0 = time.perf_counter()
        r = requests.post(
            f"{self.host}/api/chat",
            json={"model": self.model_id, "stream": False, "format": fmt,
                  "options": {"temperature": 0},
                  "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                               {"role": "user", "content": prompt}]},
            timeout=self.timeout,
        )
        r.raise_for_status()
        body = r.json()
        usage = LLMUsage(self.model_id, body.get("prompt_eval_count", 0), body.get("eval_count", 0),
                         int((time.perf_counter() - t0) * 1000))
        return parse_json(body["message"]["content"]), usage

    def extract(self, pages: list[Page], doc_type: DocType) -> ExtractionOutput:
        raw, usage = self._chat(user_prompt(pages, doc_type), response_schema(doc_type))
        return ExtractionOutput(fields=coerce_fields(raw, doc_type), usage=usage, raw=raw)

    def classify(self, pages: list[Page], candidates: list[DocType]) -> ClassifyOutput:
        fmt = {"type": "object", "properties": {"doc_type": {"type": "string"}, "confidence": {"type": "number"}},
               "required": ["doc_type", "confidence"]}
        raw, usage = self._chat(classify_prompt(pages, candidates), fmt)
        names = {d.name for d in candidates}
        doc_type = raw.get("doc_type") if raw.get("doc_type") in names else "unknown"
        return ClassifyOutput(doc_type=doc_type, confidence=float(raw.get("confidence", 0)), usage=usage)


# --------------------------------------------------------------------------- warehouse


class DuckDBWarehouse:
    """Local stand-in for Snowflake CORE. Rows are upserted by key; nested values stored as JSON."""

    REFERENCE_TABLES = {"reason_codes": "ref_reason_code", "dispute_outcomes": "dispute_outcome"}

    def __init__(self, path: str, reference_dir: str | None = None):
        import duckdb

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.con = duckdb.connect(path)
        from uif.config import repo_root

        ddl = repo_root() / "sql" / "duckdb" / "core.sql"
        if ddl.exists():
            self.con.execute(ddl.read_text())
        if reference_dir:
            self.load_reference(reference_dir)

    def load_reference(self, reference_dir: str) -> None:
        """Refresh reference tables from CSVs (Snowflake: REF_* tables maintained by their owners)."""
        for name, table in self.REFERENCE_TABLES.items():
            csv_path = Path(reference_dir) / f"{name}.csv"
            if csv_path.exists():
                self.con.execute(f"DELETE FROM {table}")
                self.con.execute(f"INSERT INTO {table} SELECT * FROM read_csv(?, header=true, all_varchar=true)",
                                 [str(csv_path)])

    def upsert(self, table: str, rows: list[dict[str, Any]], key: list[str]) -> int:
        if not rows:
            return 0
        cols = list(rows[0])
        placeholders = ", ".join("?" for _ in cols)
        self.con.execute("BEGIN")
        try:
            for row in rows:
                where = " AND ".join(f"{k} = ?" for k in key)
                self.con.execute(f"DELETE FROM {table} WHERE {where}", [row[k] for k in key])
                self.con.execute(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
                    [json.dumps(row[c], default=str) if isinstance(row[c], (dict, list)) else row[c] for c in cols],
                )
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
        return len(rows)

    def query(self, sql: str, params: list | None = None) -> list[tuple]:
        return self.con.execute(sql, params or []).fetchall()

    def close(self) -> None:
        self.con.close()
