"""When the guard gets stricter, identifiers it used to miss are still sitting in guarded/ and in
handoff requests. `uif reguard` must find and remove them."""

import re

from uif.contracts import GuardedDoc
from uif.providers import local
from uif.providers.handoff import HandoffLLM, purge_unsafe, status
from uif.runner import process_bytes
from uif.steps import guard

DOC = (b"Chargeback rebuttal. Case Number: CB-2026-000001. Reason Code: 13.1. Disputed Amount: $10.00. "
       b"Cardholder proof of delivery and invoice attached. Questions: billing @ shop-example.com\n")


def test_reguard_cleans_what_an_older_guard_missed(ctx, monkeypatch):
    ctx.providers.llm = HandoffLLM(ctx.store)
    old_email = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")  # the pre-fix pattern
    monkeypatch.setattr(local, "_EMAIL", old_email)
    run = process_bytes(ctx, DOC, "rebuttal.txt", "merchant", "test")
    assert run.pending
    rid = status(ctx.store)["pending"][0]
    assert b"billing @ shop-example.com" in ctx.store.get_bytes(f"handoff/requests/{rid}.json")

    monkeypatch.undo()  # ship the stricter guard
    assert purge_unsafe(ctx.store, ctx.providers.guard) == [rid]
    assert status(ctx.store)["pending"] == []
    guard.run(ctx, run.doc_id)
    text = " ".join(p.text for p in ctx.get_model("guarded", GuardedDoc, doc_id=run.doc_id).pages)
    assert "shop-example" not in text and "<EMAIL_" in text
