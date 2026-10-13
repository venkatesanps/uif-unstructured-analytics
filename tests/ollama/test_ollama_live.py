"""Live local-model check. Skipped unless an Ollama server answers at OLLAMA_HOST.

  ollama pull hermes3:latest && pytest -m ollama -s
"""

import os

import pytest
import requests

pytestmark = pytest.mark.ollama
HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "hermes3:latest")


def _up() -> bool:
    try:
        return requests.get(f"{HOST}/api/tags", timeout=2).ok
    except requests.RequestException:
        return False


@pytest.mark.skipif(not _up(), reason=f"no Ollama server at {HOST}")
def test_ollama_recovers_the_unseen_layout(tmp_path, golden_dir):
    from tests.conftest import make_ctx
    from uif.contracts import Validated
    from uif.runner import process_bytes

    ctx = make_ctx(tmp_path, **{"llm.kind": "ollama", "llm.ollama.model": MODEL})
    f = golden_dir / "merchant" / "statement_05_C.pdf"
    run = process_bytes(ctx, f.read_bytes(), f.name, "merchant", "test")
    val = ctx.get_model("validated", Validated, doc_id=run.doc_id)
    got = {x.field_path: x.value_norm for x in val.facts}
    print({k: (v, next(x.review_reasons for x in val.facts if x.field_path == k)) for k, v in got.items()})
    assert "gross_volume" in got, "model should find the sales total the rules baseline cannot"
