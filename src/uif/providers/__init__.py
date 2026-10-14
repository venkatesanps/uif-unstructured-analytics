"""Provider factory: config -> concrete adapters. This is the only place that knows
which runtime is active."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from uif.providers.base import GuardProvider, LLMProvider, OCRProvider, Store, Warehouse


@dataclass
class Providers:
    store: Store
    ocr: OCRProvider
    guard: GuardProvider
    llm: LLMProvider
    warehouse: Warehouse


def build_providers(cfg: dict[str, Any]) -> Providers:
    from uif.providers import local

    s = cfg["store"]
    if s["kind"] == "local":
        store = local.LocalStore(s["root"])
    elif s["kind"] == "s3":
        from uif.providers.aws import S3Store

        store = S3Store(s["bucket"], s.get("prefix", ""), s.get("kms_key_id"))
    else:
        raise ValueError(f"unknown store kind {s['kind']}")

    o = cfg["ocr"]["kind"]
    if o == "local":
        ocr = local.LocalOCR()
    elif o == "textract":
        from uif.providers.aws import TextractOCR

        ocr = TextractOCR(store=store if s["kind"] == "s3" else None, region=cfg.get("region"))
    else:
        raise ValueError(f"unknown ocr kind {o}")

    g = cfg["guard"]
    if g["kind"] == "regex":
        guard = local.RegexGuard(g["token_salt"])
    elif g["kind"] == "comprehend":
        from uif.providers.aws import ComprehendGuard

        guard = ComprehendGuard(g["token_salt"], cfg.get("region"))
    else:
        raise ValueError(f"unknown guard kind {g['kind']}")

    lcfg = cfg["llm"]
    if lcfg["kind"] == "rules":
        llm = local.RulesExtractor()
    elif lcfg["kind"] == "ollama":
        oc = lcfg["ollama"]
        llm = local.OllamaLLM(oc["host"], oc["model"], int(oc.get("timeout_s", 180)))
    elif lcfg["kind"] == "handoff":
        from uif.providers.handoff import HandoffLLM

        llm = HandoffLLM(store, (lcfg.get("handoff") or {}).get("agent", "agent"))
    elif lcfg["kind"] == "anthropic":
        from uif.providers.anthropic_api import AnthropicLLM

        a = dict(lcfg.get("anthropic") or {})
        llm = AnthropicLLM(**{k: v for k, v in a.items() if v not in (None, "")})
    elif lcfg["kind"] == "bedrock":
        from uif.providers.aws import BedrockLLM

        bc = lcfg["bedrock"]
        llm = BedrockLLM(bc["model_id"], cfg.get("region"), int(bc.get("max_tokens", 4096)),
                         tool_choice=bc.get("tool_choice", "auto"))
    else:
        raise ValueError(f"unknown llm kind {lcfg['kind']}")

    w = cfg["warehouse"]
    if w["kind"] == "duckdb":
        warehouse = local.DuckDBWarehouse(w["path"], (cfg.get("reference") or {}).get("path"))
    elif w["kind"] == "stage":
        from uif.providers.aws import StageWarehouse

        warehouse = StageWarehouse(store, w.get("prefix", "publish"))
    else:
        raise ValueError(f"unknown warehouse kind {w['kind']}")

    return Providers(store, ocr, guard, llm, warehouse)
