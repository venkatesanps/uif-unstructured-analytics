"""Claude via the Messages API, directly or through a corporate gateway that exposes it.

Configurable for gateways: base_url, the auth header (x-api-key or Authorization: Bearer),
extra headers, and the model name your gateway uses.

Tool choice: the newest Claude models reject a forced tool (`tool_choice: {"type": "tool"}`
returns 400 on Opus 5.5 / Sonnet 5.5 per the tool-use docs), so the default is `auto` with a
system instruction to call the tool, plus a fallback that parses JSON from a text block.
Set `tool_choice: tool` only for models that still accept it. Strict tool mode is not used:
it caps nullable unions at 16 per request and these schemas need more. The validator
(grounding, value-in-quote, rules) is the safety net either way."""

from __future__ import annotations

import os
import time
from typing import Any

import requests

from uif.contracts import Page
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

CALL_TOOL = ("\nAlways answer by calling the {tool} tool exactly once with the full result. "
             "Do not answer in plain text.")


def pick_tool_input(content: list[dict[str, Any]], tool: str) -> dict[str, Any]:
    """tool_use input if present, else JSON parsed from the first text block."""
    for block in content:
        if block.get("type") == "tool_use" and block.get("name") == tool:
            return block.get("input") or {}
    for block in content:
        if block.get("type") == "text" and "{" in block.get("text", ""):
            return parse_json(block["text"])
    raise ValueError(f"model returned neither a {tool} call nor JSON text")


class AnthropicLLM:
    def __init__(self, model: str, base_url: str = "https://api.anthropic.com", api_key_env: str = "ANTHROPIC_API_KEY",
                 auth: str = "x-api-key", anthropic_version: str = "2023-06-01", tool_choice: str = "auto",
                 max_tokens: int = 4096, temperature: float | None = None, timeout_s: int = 120, extra_headers: dict[str, str] | None = None,
                 session: Any = None):
        if not model:
            raise ValueError("llm.anthropic.model is not set")
        self.model_id, self.base_url = model, base_url.rstrip("/")
        self.api_key_env, self.auth, self.version = api_key_env, auth, anthropic_version
        self.tool_choice, self.max_tokens, self.timeout = tool_choice, int(max_tokens), int(timeout_s)
        self.temperature = None if temperature in (None, "") else float(temperature)  # omitted unless set; not every model accepts sampling params
        self.extra_headers = extra_headers or {}
        self.http = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise RuntimeError(f"{self.api_key_env} is not set")
        auth = {"Authorization": f"Bearer {key}"} if self.auth == "bearer" else {"x-api-key": key}
        return {"content-type": "application/json", "anthropic-version": self.version, **auth, **self.extra_headers}

    def call_raw(self, system: str, prompt: str, tool: str, schema: dict) -> tuple[dict, LLMUsage]:
        """Answer a prompt verbatim (used to replay handoff requests for parity checks)."""
        return self._call(prompt, tool, schema, system=system)

    def _call(self, prompt: str, tool: str, schema: dict, system: str = SYSTEM_PROMPT) -> tuple[dict, LLMUsage]:
        body = {
            "model": self.model_id,
            "max_tokens": self.max_tokens,
            "system": system + CALL_TOOL.format(tool=tool),
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"name": tool, "description": "Record the result.", "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": tool} if self.tool_choice == "tool" else {"type": "auto"},
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        t0 = time.perf_counter()
        r = self.http.post(f"{self.base_url}/v1/messages", json=body, headers=self._headers(), timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Messages API {r.status_code}: {r.text[:300]}")
        data = r.json()
        u = data.get("usage", {})
        usage = LLMUsage(data.get("model", self.model_id), u.get("input_tokens", 0), u.get("output_tokens", 0),
                         int((time.perf_counter() - t0) * 1000))
        return pick_tool_input(data.get("content", []), tool), usage

    def extract(self, pages: list[Page], doc_type: DocType) -> ExtractionOutput:
        raw, usage = self._call(user_prompt(pages, doc_type), "record_extraction", response_schema(doc_type))
        return ExtractionOutput(fields=coerce_fields(raw, doc_type), usage=usage, raw=raw)

    def classify(self, pages: list[Page], candidates: list[DocType]) -> ClassifyOutput:
        schema = {"type": "object", "properties": {"doc_type": {"type": "string"}, "confidence": {"type": "number"}},
                  "required": ["doc_type", "confidence"]}
        raw, usage = self._call(classify_prompt(pages, candidates), "record_classification", schema)
        names = {d.name for d in candidates}
        doc_type = raw.get("doc_type") if raw.get("doc_type") in names else "unknown"
        return ClassifyOutput(doc_type=doc_type, confidence=float(raw.get("confidence", 0)), usage=usage)
