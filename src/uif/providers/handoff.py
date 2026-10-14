"""Agent handoff: extraction by whatever agent you are allowed to use (Claude Code, Copilot
agent mode, a Claude agent in your firm's tooling) with no API key or local model.

Round trip:
  1. `uif run ... --llm handoff` writes one request per document to handoff/requests/<id>.json
     (tokenized pages + the exact system/user prompt + response schema) and parks the document.
  2. The agent follows AGENT_EXTRACT.md: reads each request, writes handoff/responses/<id>.json.
  3. `uif run ... --llm handoff --force` picks up the responses; validate/publish run as usual.

Requests contain only guard-tokenized text, the same text a hosted model would see. The agent
must never open raw/, restricted/, the source files or golden labels."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from uif.contracts import Page, utcnow
from uif.providers.base import ClassifyOutput, ExtractionOutput, LLMUsage
from uif.providers.llm_common import SYSTEM_PROMPT, classify_prompt, coerce_fields, response_schema, user_prompt
from uif.registry import DocType

REQ, RESP = "handoff/requests", "handoff/responses"


class HandoffPending(Exception):
    def __init__(self, request_id: str, key: str):
        super().__init__(f"waiting for agent response {request_id}")
        self.request_id, self.key = request_id, key


def request_id(kind: str, pages: list[Page], *parts: str) -> str:
    h = hashlib.sha256(kind.encode())
    for p in pages:
        h.update(p.text.encode())
    for part in parts:
        h.update(part.encode())
    return h.hexdigest()[:16]


class HandoffLLM:
    def __init__(self, store, default_agent: str = "agent"):
        self.store, self.default_agent = store, default_agent
        self.model_id = f"handoff:{default_agent}"

    def _exchange(self, rid: str, request: dict[str, Any]) -> tuple[dict[str, Any], LLMUsage]:
        resp_key = f"{RESP}/{rid}.json"
        if self.store.exists(resp_key):
            resp = json.loads(self.store.get_bytes(resp_key))
            agent = resp.get("agent") or self.default_agent
            return resp, LLMUsage(f"handoff:{agent}", int(resp.get("tokens_in", 0)), int(resp.get("tokens_out", 0)))
        req_key = f"{REQ}/{rid}.json"
        if not self.store.exists(req_key):
            self.store.put_bytes(req_key, json.dumps({"request_id": rid, "created_ts": utcnow(), **request},
                                                     indent=2).encode())
        raise HandoffPending(rid, req_key)

    def extract(self, pages: list[Page], doc_type: DocType) -> ExtractionOutput:
        rid = request_id("extract", pages, doc_type.name, doc_type.version, doc_type.prompt_version)
        resp, usage = self._exchange(rid, {
            "kind": "extract",
            "doc_type": doc_type.name,
            "schema_version": doc_type.version,
            "prompt_version": doc_type.prompt_version,
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt": user_prompt(pages, doc_type),
            "response_schema": response_schema(doc_type),
            "respond_with": {"request_id": rid, "agent": "<your agent/model name>",
                             "fields": "<object matching response_schema>"},
        })
        return ExtractionOutput(fields=coerce_fields(resp.get("fields", {}), doc_type), usage=usage, raw=resp)

    def classify(self, pages: list[Page], candidates: list[DocType]) -> ClassifyOutput:
        rid = request_id("classify", pages, *sorted(d.name for d in candidates))
        resp, usage = self._exchange(rid, {
            "kind": "classify",
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt": classify_prompt(pages, candidates),
            "respond_with": {"request_id": rid, "agent": "<your agent/model name>",
                             "doc_type": "<one of the types or unknown>", "confidence": "<0-1>"},
        })
        names = {d.name for d in candidates}
        doc_type = resp.get("doc_type") if resp.get("doc_type") in names else "unknown"
        return ClassifyOutput(doc_type=doc_type, confidence=float(resp.get("confidence", 0)), usage=usage)


def status(store) -> dict[str, list[str]]:
    reqs = {k.rsplit("/", 1)[-1][:-5] for k in store.list(REQ) if k.endswith(".json")}
    resps = {k.rsplit("/", 1)[-1][:-5] for k in store.list(RESP) if k.endswith(".json")}
    return {"pending": sorted(reqs - resps), "answered": sorted(reqs & resps), "orphan": sorted(resps - reqs)}


def check(store) -> list[str]:
    """Structural checks on agent responses before the pipeline consumes them."""
    problems = []
    for rid in status(store)["answered"]:
        req = json.loads(store.get_bytes(f"{REQ}/{rid}.json"))
        try:
            resp = json.loads(store.get_bytes(f"{RESP}/{rid}.json"))
        except json.JSONDecodeError as exc:
            problems.append(f"{rid}: response is not valid JSON ({exc})")
            continue
        if resp.get("request_id") != rid:
            problems.append(f"{rid}: request_id mismatch")
        if req["kind"] == "extract":
            fields = resp.get("fields")
            if not isinstance(fields, dict):
                problems.append(f"{rid}: missing 'fields' object")
                continue
            expected = set(req["response_schema"]["properties"])
            if set(fields) - expected:
                problems.append(f"{rid}: unknown fields {sorted(set(fields) - expected)}")
            for name, item in fields.items():
                if not isinstance(item, dict) or not {"value", "page", "quote", "confidence"} <= set(item):
                    problems.append(f"{rid}: {name} must have value, page, quote, confidence")
                elif item["value"] not in (None, [], "") and not item.get("quote"):
                    problems.append(f"{rid}: {name} has a value but no quote")
    return problems


def purge_unsafe(store, guard) -> list[str]:
    """After the guard gets stricter, any request whose text it would now change still holds an
    identifier the old guard missed. Delete it and its response; the next run re-issues it."""
    removed = []
    for key in store.list(REQ):
        if not key.endswith(".json"):
            continue
        req = json.loads(store.get_bytes(key))
        text = req.get("user_prompt", "")
        rescanned, findings = guard.scan([Page(page=1, text=text)])
        if findings or rescanned[0].text != text:
            rid = req["request_id"]
            store.delete(key)
            store.delete(f"{RESP}/{rid}.json")
            removed.append(rid)
    return removed
