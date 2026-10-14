"""AWS adapters: S3, Textract, Comprehend PII, Bedrock (Converse API with a forced
tool call for schema-constrained output), and a Snowpipe staging warehouse.
boto3 is imported lazily so local runs don't need it."""

from __future__ import annotations

import json
import time
from typing import Any

from uif.contracts import GuardFinding, Page
from uif.providers.base import ClassifyOutput, ExtractionOutput, LLMUsage
from uif.providers.llm_common import SYSTEM_PROMPT, classify_prompt, coerce_fields, response_schema, user_prompt
from uif.providers.anthropic_api import CALL_TOOL, pick_tool_input
from uif.providers.local import RegexGuard
from uif.registry import DocType


def _client(service: str, region: str | None = None, retries: int | None = None):
    import boto3

    kw = {"region_name": region} if region else {}
    if retries:  # adaptive client-side rate limiting: batch answering hits Bedrock throttles
        from botocore.config import Config

        kw["config"] = Config(retries={"max_attempts": retries, "mode": "adaptive"}, read_timeout=300)
    return boto3.client(service, **kw)


class S3Store:
    def __init__(self, bucket: str, prefix: str = "", kms_key_id: str | None = None, client=None):
        if not bucket:
            raise ValueError("UIF_BUCKET is not set")
        self.bucket, self.prefix, self.kms = bucket, prefix.strip("/"), kms_key_id or None
        self.s3 = client or _client("s3")

    def _k(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put_bytes(self, key: str, data: bytes) -> str:
        extra = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.kms} if self.kms else {}
        self.s3.put_object(Bucket=self.bucket, Key=self._k(key), Body=data, **extra)
        return self.uri(key)

    def get_bytes(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.bucket, Key=self._k(key))["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=self._k(key))
            return True
        except self.s3.exceptions.ClientError:
            return False

    def list(self, prefix: str) -> list[str]:
        out, token = [], None
        strip = len(self.prefix) + 1 if self.prefix else 0
        while True:
            kw = {"Bucket": self.bucket, "Prefix": self._k(prefix)}
            if token:
                kw["ContinuationToken"] = token
            resp = self.s3.list_objects_v2(**kw)
            out += [o["Key"][strip:] for o in resp.get("Contents", [])]
            if not resp.get("IsTruncated"):
                return sorted(out)
            token = resp["NextContinuationToken"]

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{self._k(key)}"

    def delete(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=self._k(key))


class TextractOCR:
    """Sync API for images and single-page PDFs; async job for multi-page PDFs (needs S3)."""

    def __init__(self, store: S3Store | None = None, region: str | None = None, poll_s: float = 2.0):
        self.textract = _client("textract", region)
        self.store, self.poll_s = store, poll_s

    @staticmethod
    def _pages_from_blocks(blocks: list[dict]) -> list[Page]:
        by_page: dict[int, list[str]] = {}
        for b in blocks:
            if b["BlockType"] == "LINE":
                by_page.setdefault(b.get("Page", 1), []).append(b["Text"])
        return [Page(page=p, text="\n".join(lines)) for p, lines in sorted(by_page.items())]

    def to_pages(self, data: bytes, mime_type: str, file_name: str) -> tuple[list[Page], str]:
        if mime_type == "message/rfc822":  # body as text, attachments through Textract
            from uif.providers.local import email_pages

            return email_pages(data, self.to_pages)
        if not (mime_type == "application/pdf" or mime_type.startswith("image/")):
            from uif.providers.local import LocalOCR  # text, email and html need no OCR

            return LocalOCR(tesseract_cmd="").to_pages(data, mime_type, file_name)
        try:
            resp = self.textract.detect_document_text(Document={"Bytes": data})
            return self._pages_from_blocks(resp["Blocks"]), "textract-sync"
        except self.textract.exceptions.UnsupportedDocumentException:
            if not self.store:
                raise
        key = f"restricted/ocr-staging/{file_name}"  # raw bytes: stays inside the PCI boundary
        self.store.put_bytes(key, data)
        job = self.textract.start_document_text_detection(
            DocumentLocation={"S3Object": {"Bucket": self.store.bucket, "Name": self.store._k(key)}})
        blocks, token = [], None
        while True:
            kw = {"JobId": job["JobId"]}
            if token:
                kw["NextToken"] = token
            resp = self.textract.get_document_text_detection(**kw)
            if resp["JobStatus"] == "IN_PROGRESS":
                time.sleep(self.poll_s)
                continue
            if resp["JobStatus"] != "SUCCEEDED":
                raise RuntimeError(f"Textract job failed: {resp.get('StatusMessage')}")
            blocks += resp["Blocks"]
            token = resp.get("NextToken")
            if not token:
                return self._pages_from_blocks(blocks), "textract-async"


class ComprehendGuard(RegexGuard):
    """Regex + Luhn pass first (deterministic, never skipped), then Comprehend PII for
    names, addresses and anything the regexes miss."""

    KINDS = {"NAME": "name", "ADDRESS": "address", "SSN": "ssn", "BANK_ACCOUNT_NUMBER": "bank_account",
             "CREDIT_DEBIT_NUMBER": "pan", "EMAIL": "email", "PHONE": "phone", "PASSPORT_NUMBER": "passport",
             "DRIVER_ID": "driver_id"}

    def __init__(self, token_salt: str, region: str | None = None, min_score: float = 0.8):
        super().__init__(token_salt)
        self.comprehend = _client("comprehend", region)
        self.min_score = min_score

    def scan(self, pages: list[Page]) -> tuple[list[Page], list[GuardFinding]]:
        pages, findings = super().scan(pages)
        out = []
        for p in pages:
            text = p.text
            ents = self.comprehend.detect_pii_entities(Text=text[:99_000], LanguageCode="en")["Entities"]
            for e in sorted(ents, key=lambda e: e["BeginOffset"], reverse=True):
                kind = self.KINDS.get(e["Type"])
                span = text[e["BeginOffset"]:e["EndOffset"]]
                if not kind or e["Score"] < self.min_score or span.startswith("<"):
                    continue
                tok = self.token(kind, span)
                findings.append(GuardFinding(kind=kind, page=p.page, token=tok))
                text = text[:e["BeginOffset"]] + tok + text[e["EndOffset"]:]
            out.append(Page(page=p.page, text=text))
        return out, findings


class BedrockLLM:
    def __init__(self, model_id: str, region: str | None = None, max_tokens: int = 4096, client=None,
                 tool_choice: str = "auto"):
        if not model_id:
            raise ValueError("UIF_BEDROCK_MODEL_ID is not set")
        self.model_id, self.max_tokens, self.tool_choice = model_id, max_tokens, tool_choice
        self.brt = client or _client("bedrock-runtime", region, retries=8)

    def call_raw(self, system: str, prompt: str, tool_name: str, schema: dict) -> tuple[dict, LLMUsage]:
        """Answer a prompt verbatim (used to replay handoff requests for parity checks)."""
        return self._tool_call(prompt, tool_name, schema, system=system)

    def _tool_call(self, prompt: str, tool_name: str, schema: dict, system: str = SYSTEM_PROMPT
                   ) -> tuple[dict, LLMUsage]:
        t0 = time.perf_counter()
        # Newest Claude models reject a forced tool; default to auto + instruction + text fallback.
        choice = {"tool": {"name": tool_name}} if self.tool_choice == "tool" else {"auto": {}}
        resp = self.brt.converse(
            modelId=self.model_id,
            system=[{"text": system + CALL_TOOL.format(tool=tool_name)}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": self.max_tokens},
            toolConfig={"tools": [{"toolSpec": {"name": tool_name, "description": "Record the result.",
                                                "inputSchema": {"json": schema}}}],
                        "toolChoice": choice},
        )
        blocks = resp["output"]["message"]["content"]
        result = pick_tool_input([{"type": "tool_use", "name": b["toolUse"]["name"], "input": b["toolUse"]["input"]}
                                  if "toolUse" in b else {"type": "text", "text": b.get("text", "")}
                                  for b in blocks], tool_name)
        u = resp.get("usage", {})
        return result, LLMUsage(self.model_id, u.get("inputTokens", 0), u.get("outputTokens", 0),
                                int((time.perf_counter() - t0) * 1000))

    def extract(self, pages: list[Page], doc_type: DocType) -> ExtractionOutput:
        raw, usage = self._tool_call(user_prompt(pages, doc_type), "record_extraction", response_schema(doc_type))
        return ExtractionOutput(fields=coerce_fields(raw, doc_type), usage=usage, raw=raw)

    def classify(self, pages: list[Page], candidates: list[DocType]) -> ClassifyOutput:
        schema = {"type": "object", "properties": {"doc_type": {"type": "string"}, "confidence": {"type": "number"}},
                  "required": ["doc_type", "confidence"]}
        raw, usage = self._tool_call(classify_prompt(pages, candidates), "record_classification", schema)
        names = {d.name for d in candidates}
        doc_type = raw.get("doc_type") if raw.get("doc_type") in names else "unknown"
        return ClassifyOutput(doc_type=doc_type, confidence=float(raw.get("confidence", 0)), usage=usage)


class StageWarehouse:
    """Writes NDJSON per table under <prefix>/<table>/ in the store. Snowpipe (auto-ingest
    on the bucket) loads it into RAW; Snowflake tasks MERGE into CORE (sql/snowflake/)."""

    def __init__(self, store, prefix: str = "publish"):
        self.store, self.prefix = store, prefix.strip("/")

    def upsert(self, table: str, rows: list[dict[str, Any]], key: list[str]) -> int:
        if not rows:
            return 0
        part = "-".join(str(rows[0][k]) for k in key[:1])
        body = "\n".join(json.dumps({"_table": table, "_key": key, **r}, default=str) for r in rows)
        stamp = time.strftime("%Y%m%dT%H%M%S")
        self.store.put_bytes(f"{self.prefix}/{table.lower()}/{part}-{stamp}.ndjson", body.encode())
        return len(rows)
