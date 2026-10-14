"""Ports. Steps depend only on these protocols; config picks the adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from uif.contracts import GuardFinding, Page
from uif.registry import DocType


class Store(Protocol):
    def put_bytes(self, key: str, data: bytes) -> str: ...
    def get_bytes(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...
    def uri(self, key: str) -> str: ...
    def delete(self, key: str) -> None: ...


class OCRProvider(Protocol):
    def to_pages(self, data: bytes, mime_type: str, file_name: str) -> tuple[list[Page], str]: ...


class GuardProvider(Protocol):
    def scan(self, pages: list[Page]) -> tuple[list[Page], list[GuardFinding]]: ...


@dataclass
class LLMUsage:
    model_id: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


@dataclass
class ExtractionOutput:
    fields: dict[str, dict[str, Any]]  # field -> {value, page, quote, confidence}
    usage: LLMUsage
    raw: Any = None


@dataclass
class ClassifyOutput:
    doc_type: str
    confidence: float
    usage: LLMUsage
    scores: dict[str, float] = field(default_factory=dict)


class LLMProvider(Protocol):
    model_id: str

    def extract(self, pages: list[Page], doc_type: DocType) -> ExtractionOutput: ...
    def classify(self, pages: list[Page], candidates: list[DocType]) -> ClassifyOutput: ...


class Warehouse(Protocol):
    def upsert(self, table: str, rows: list[dict[str, Any]], key: list[str]) -> int: ...
