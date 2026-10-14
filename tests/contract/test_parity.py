"""Parity tooling: providers answer handoff requests verbatim, bundles carry only tokenized text,
the diff finds disagreements, and saved golden answers still replay cleanly."""

import io
import json
import shutil
import zipfile
from pathlib import Path

from uif import parity
from uif.contracts import GuardedDoc
from uif.providers.aws import BedrockLLM
from uif.providers.handoff import (HandoffLLM, answer_pending, export_bundle, import_bundle,
                                   pages_from_prompt, status)
from uif.runner import process_bytes

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "evals" / "golden"


class _FakeBedrock:
    """Answers every extraction with the merchant_name it can see; records what it was sent."""

    def __init__(self):
        self.calls = []

    def converse(self, **kw):
        self.calls.append(kw)
        prompt = kw["messages"][0]["content"][0]["text"]
        name = next((l.split(":", 1)[1].split("(")[0].strip() for l in prompt.splitlines() if l.startswith("Merchant:")), None)
        return {"output": {"message": {"content": [{"toolUse": {"name": "record_extraction", "input": {
            "merchant_name": {"value": name, "page": 1, "quote": f"Merchant: {name}", "confidence": 0.9}}}}]}},
            "usage": {"inputTokens": 1000, "outputTokens": 100}}


def _pending_request(ctx, golden_dir, rel="internal/note_00.txt"):
    ctx.providers.llm = HandoffLLM(ctx.store)
    f = golden_dir / rel
    run = process_bytes(ctx, f.read_bytes(), f.name, "internal", "test")
    return run, status(ctx.store)["pending"][0]


def test_bedrock_answers_requests_with_their_own_prompts(ctx, golden_dir):
    run, rid = _pending_request(ctx, golden_dir)
    req = json.loads(ctx.store.get_bytes(f"handoff/requests/{rid}.json"))
    fake = _FakeBedrock()
    out = answer_pending(ctx.store, BedrockLLM("m", client=fake), ctx.registry, label="bedrock")
    assert out == {"answered": 1, "failed": {}, "remaining": 0}
    sent = fake.calls[0]
    assert sent["messages"][0]["content"][0]["text"] == req["user_prompt"]          # verbatim prompt
    assert sent["system"][0]["text"].startswith(req["system_prompt"])                  # verbatim system
    assert sent["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"]["json"] == req["response_schema"]
    resp = json.loads(ctx.store.get_bytes(f"handoff/responses/{rid}.json"))
    assert resp["agent"] == "bedrock:m" and resp["tokens_in"] == 1000
    assert set(resp["fields"]) == set(req["response_schema"]["properties"])
    # and the pipeline resumes from the Bedrock answer like any other
    again = process_bytes(ctx, (golden_dir / "internal/note_00.txt").read_bytes(), "note_00.txt", "internal",
                          "test", force=True)
    assert again.ok and not again.pending


def test_pages_round_trip_through_the_prompt(ctx, golden_dir):
    run, rid = _pending_request(ctx, golden_dir, "internal/note_01.eml")
    req = json.loads(ctx.store.get_bytes(f"handoff/requests/{rid}.json"))
    guarded = ctx.get_model("guarded", GuardedDoc, doc_id=run.doc_id).pages
    assert [(p.page, p.text) for p in pages_from_prompt(req["user_prompt"])] == [(p.page, p.text.strip()) for p in guarded]


def test_bundles_round_trip_and_refuse_untokenized_text(ctx, golden_dir, tmp_path):
    _pending_request(ctx, golden_dir)
    data = export_bundle(ctx.store, "requests")
    from tests.conftest import make_ctx

    other = make_ctx(tmp_path / "aws-sim")
    assert import_bundle(other.store, data, guard=other.providers.guard)["loaded"] == 1
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("manifest.json", json.dumps({"kind": "requests"}))
        z.writestr("requests/x.json", json.dumps({"request_id": "x", "kind": "extract",
                                                 "user_prompt": "card 4111 1111 1111 1111"}))
    res = import_bundle(other.store, bad.getvalue(), guard=other.providers.guard)
    assert res["loaded"] == 0 and res["refused"] == ["requests/x.json"]


def test_diff_finds_disagreements_and_missing_answers(ctx, tmp_path):
    a = parity.load_dir(GOLDEN / "answers" / "claude-code")
    reqs = parity.load_dir(GOLDEN / "requests")
    same = parity.diff(reqs, a, a, ctx.registry)
    assert same["agreement"] == 1.0 and parity.gate(same) == []
    b = json.loads(json.dumps(a))
    rid = next(r for r, q in reqs.items() if q.get("doc_type") == "processor_statement")
    b[rid]["fields"]["gross_volume"]["value"] = 1.0
    del b[next(r for r in reqs if r != rid)]
    rep = parity.diff(reqs, a, b, ctx.registry)
    assert any(d["field"] == "gross_volume" and d["request_id"] == rid for d in rep["disagreements"])
    assert rep["by_field"]["processor_statement.gross_volume"]["rate"] < 1
    assert any("unanswered" in f for f in parity.gate(rep))
    md = parity.render_markdown(rep, ("agent", "bedrock"))
    assert "FAIL" in md and "gross_volume" in md and "Requests:" in md


def test_saved_golden_answers_still_match_the_generator(golden_dir):
    # If the synthetic generator, guard or prompts change, request ids change and this fails:
    # regenerate requests and re-answer before trusting any parity report.
    report = parity.replay_eval(GOLDEN / "answers" / "claude-code", golden_dir)
    assert report["unanswered_documents"] == 0
    from uif.evals import gate

    assert gate(report) == [] and report["required_f1"] == 1.0


def test_bundle_import_uses_the_regex_guard_even_when_the_runtime_guard_is_broader(ctx, golden_dir, tmp_path):
    from uif.cli import bundle_guard
    from tests.conftest import make_ctx

    _pending_request(ctx, golden_dir, "dispute/rebuttal_03.eml")  # invoice names "A. Customer"
    data = export_bundle(ctx.store, "requests")
    other = make_ctx(tmp_path / "aws-like")

    class NameFlaggingGuard:  # stands in for Comprehend, which also flags person names
        def scan(self, pages):
            from uif.contracts import GuardFinding
            return pages, [GuardFinding(kind="name", page=p.page, token="<NAME_x>") for p in pages if "Customer" in p.text]

    assert import_bundle(other.store, data, guard=NameFlaggingGuard())["refused"]      # what would have happened
    assert import_bundle(other.store, data, guard=bundle_guard(other))["refused"] == []  # what the CLI does
