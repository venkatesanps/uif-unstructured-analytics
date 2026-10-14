"""Step contracts. Every step reads and writes these models as JSON, so the same
step runs unchanged in the local runner, a Lambda, or an ECS task."""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class SourceGroup(str, Enum):
    merchant = "merchant"
    external = "external"
    internal = "internal"


class SensitivityTier(str, Enum):
    public = "public"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"  # contained PAN or government ID before tokenization


class ReviewStatus(str, Enum):
    auto_accepted = "auto_accepted"
    needs_review = "needs_review"
    accepted = "accepted"
    corrected = "corrected"
    rejected = "rejected"


class DocEnvelope(BaseModel):
    doc_id: str
    content_sha256: str
    source_group: SourceGroup
    source_system: str
    submitter: str | None = None
    received_ts: str = Field(default_factory=utcnow)
    file_name: str
    mime_type: str
    storage_uri: str
    page_count: int | None = None
    language: str | None = None
    sensitivity_tier: SensitivityTier = SensitivityTier.internal


class Page(BaseModel):
    page: int  # 1-based
    text: str


class NormalizedDoc(BaseModel):
    doc_id: str
    pages: list[Page]
    method: str  # e.g. "pdfplumber", "tesseract", "textract", "email", "text"


class GuardFinding(BaseModel):
    kind: str  # pan, ssn, email, phone, bank_account
    page: int
    token: str


class GuardedDoc(BaseModel):
    doc_id: str
    pages: list[Page]  # tokenized text; the only text any model may see
    findings: list[GuardFinding] = []
    sensitivity_tier: SensitivityTier
    quarantined: bool = False


class Classification(BaseModel):
    doc_id: str
    doc_type: str  # "unknown" when unsure
    confidence: float
    taxonomy_version: str
    method: str  # "keywords" | "llm"
    model_id: str | None = None


class FieldValue(BaseModel):
    """What an extractor returns per field. Evidence is mandatory for non-null values."""

    value: Any = None
    page: int | None = None
    quote: str | None = None
    confidence: float = 0.0


class ExtractorRun(BaseModel):
    run_id: str
    doc_id: str
    agent: str
    model_id: str
    prompt_version: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    started_ts: str = Field(default_factory=utcnow)


class Extraction(BaseModel):
    doc_id: str
    doc_type: str
    schema_version: str
    fields: dict[str, FieldValue]
    run: ExtractorRun


class EntityLink(BaseModel):
    doc_id: str
    merchant_id: str | None
    mid: str | None
    legal_name: str | None
    match_method: str  # mid_exact | name_fuzzy | none
    match_score: float


class Fact(BaseModel):
    fact_id: str
    doc_id: str
    schema_name: str
    schema_version: str
    field_path: str
    value_raw: Any
    value_norm: Any
    data_type: str
    confidence: float
    evidence_page: int | None
    evidence_quote: str | None
    run_id: str
    review_status: ReviewStatus
    review_reasons: list[str] = []


class ReviewTask(BaseModel):
    task_id: str
    doc_id: str
    fact_ids: list[str]
    reason: str
    created_ts: str = Field(default_factory=utcnow)
    decision: ReviewStatus | None = None
    corrected_value: Any = None


class Validated(BaseModel):
    doc_id: str
    facts: list[Fact]
    review_tasks: list[ReviewTask]
    rule_failures: list[str] = []


class StepResult(BaseModel):
    """Small status every step returns to the orchestrator."""

    doc_id: str
    step: str
    ok: bool
    output_key: str | None = None
    detail: str | None = None
    halt: bool = False  # stop the pipeline for this doc (e.g. quarantined)
    pending: bool = False  # waiting on an external agent (handoff); rerun to resume
