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
        ocr = local.LocalOCR(transcriber=build_transcriber(cfg))
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

    llm = build_llm(cfg, cfg["llm"]["kind"], store)

    w = cfg["warehouse"]
    if w["kind"] == "duckdb":
        warehouse = local.DuckDBWarehouse(w["path"], (cfg.get("reference") or {}).get("path"))
    elif w["kind"] == "stage":
        from uif.providers.aws import StageWarehouse

        warehouse = StageWarehouse(store, w.get("prefix", "publish"))
    else:
        raise ValueError(f"unknown warehouse kind {w['kind']}")

    return Providers(store, ocr, guard, llm, warehouse)


def build_llm(cfg: dict[str, Any], kind: str, store=None):
    """One extractor by kind, configured from cfg["llm"][<kind>]. Also used by `uif handoff answer`."""
    from uif.providers import local

    lcfg = cfg["llm"]
    if kind == "rules":
        return local.RulesExtractor()
    if kind == "ollama":
        oc = lcfg["ollama"]
        return local.OllamaLLM(oc["host"], oc["model"], int(oc.get("timeout_s", 180)))
    if kind == "handoff":
        from uif.providers.handoff import HandoffLLM

        return HandoffLLM(store, (lcfg.get("handoff") or {}).get("agent", "agent"))
    if kind == "anthropic":
        from uif.providers.anthropic_api import AnthropicLLM

        a = dict(lcfg.get("anthropic") or {})
        return AnthropicLLM(**{k: v for k, v in a.items() if v not in (None, "")})
    if kind == "bedrock":
        from uif.providers.aws import BedrockLLM

        bc = lcfg.get("bedrock") or {}
        return BedrockLLM(bc.get("model_id"), cfg.get("region"), int(bc.get("max_tokens", 4096)),
                          tool_choice=bc.get("tool_choice", "auto"))
    raise ValueError(f"unknown llm kind {kind}")


def build_transcriber(cfg: dict[str, Any]):
    """ocr.transcriber: auto (best installed: whisper.cpp, then pocketsphinx) | whisper | pocketsphinx |
    reference:<labels dir> (replays labelled scripts; tests extraction apart from recognition)."""
    from uif.providers import formats as fmt

    choice = str((cfg.get("ocr") or {}).get("transcriber") or "auto")
    if choice == "auto":
        return fmt.default_transcriber()
    if choice == "whisper":
        return fmt.WhisperCppTranscriber()
    if choice == "pocketsphinx":
        return fmt.PocketSphinxTranscriber()
    if choice.startswith("reference:"):
        from uif.synth_audio import ReferenceTranscriber

        return ReferenceTranscriber(choice.split(":", 1)[1])
    raise ValueError(f"unknown transcriber {choice}")
