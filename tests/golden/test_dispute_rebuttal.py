"""Dispute rebuttal packets: multi-document emails, image-only evidence pages, reference-data
rules, and the evidence-completeness marts."""

import json

from uif.contracts import GuardedDoc, NormalizedDoc, ReviewStatus, Validated
from uif.providers.local import RegexGuard
from uif.contracts import Page
from uif.runner import process_bytes


def _doc(report, suffix):
    return next(d for d in report["documents_detail"] if d["file"].endswith(suffix))


def test_all_rebuttals_classified_and_known_layouts_extract_cleanly(processed):
    _, report = processed
    docs = [d for d in report["documents_detail"] if d["file"].startswith("dispute/")]
    assert len(docs) == 6 and all(d["doc_type"] == "dispute_rebuttal" for d in docs)
    for d in docs:
        if not d["file"].endswith("_05.eml"):  # 05 is the unseen freeform layout
            assert d["wrong"] == [], d


def test_email_attachments_become_labelled_pages_including_ocr_of_images(ctx, golden_dir):
    f = golden_dir / "dispute" / "rebuttal_00.eml"  # body + invoice PDF + delivery screenshot PNG
    run = process_bytes(ctx, f.read_bytes(), f.name, "merchant", "test")
    norm = ctx.get_model("normalized", NormalizedDoc, doc_id=run.doc_id)
    assert "tesseract" in norm.method and len(norm.pages) == 3
    png_page = next(p for p in norm.pages if "proof_of_delivery.png" in p.text)
    assert "delivered on" in png_page.text.lower() and "signed by" in png_page.text.lower()


def test_card_number_inside_an_attachment_is_tokenized(ctx, golden_dir):
    f = golden_dir / "dispute" / "rebuttal_03.eml"
    run = process_bytes(ctx, f.read_bytes(), f.name, "merchant", "test")
    guarded = ctx.get_model("guarded", GuardedDoc, doc_id=run.doc_id)
    text = " ".join(p.text for p in guarded.pages)
    assert "5555 5555 5555 4444" not in text and "<PAN_" in text


def test_long_grouped_digit_runs_are_not_mistaken_for_cards():
    # The second half is a Luhn-valid Visa test number, but it sits inside one 32-digit grouped run
    # (container/tracking style). A PAN may not start or end inside a longer run.
    run = "1000 0000 0000 0000 4111 1111 1111 1111"
    pages, findings = RegexGuard("s").scan([Page(page=1, text=f"Container ID {run} received")])
    assert findings == [] and run in pages[0].text
    # ...while a real card number next to an expiry or CVV is still caught.
    _, findings = RegexGuard("s").scan([Page(page=1, text="Card 4111 1111 1111 1111 exp 12/27 CVV 123")])
    assert [f.kind for f in findings] == ["pan"]


def test_reason_code_must_exist_for_the_network(ctx, golden_dir):
    f = golden_dir / "dispute" / "rebuttal_01.pdf"  # mastercard 4837
    data = f.read_bytes()
    run = process_bytes(ctx, data, f.name, "merchant", "test")
    from uif.contracts import Extraction
    from uif.steps import validate

    ext = ctx.get_model("extraction", Extraction, doc_id=run.doc_id)
    ext.fields["card_network"].value = "visa"  # 4837 is not a Visa code
    ctx.put_model("extraction", ext, doc_id=run.doc_id)
    validate.run(ctx, run.doc_id)
    val = ctx.get_model("validated", Validated, doc_id=run.doc_id)
    net = next(x for x in val.facts if x.field_path == "card_network")
    assert net.review_status == ReviewStatus.needs_review
    assert "rule:network_matches_code" in net.review_reasons


def test_unseen_freeform_packet_goes_to_review(processed):
    _, report = processed
    doc = _doc(report, "rebuttal_05.eml")
    assert any(r.startswith("missing_required") for r in doc["review_tasks"])


def test_evidence_marts(processed, golden_dir):
    c, _ = processed
    wh = c.providers.warehouse
    labels = {json.loads(p.read_text())["fields"]["case_number"]: json.loads(p.read_text())
              for p in (golden_dir / "labels").glob("rebuttal_*.json")}
    rows = wh.query("select case_number, missing_evidence, evidence_completeness from mart_dispute_evidence "
                    "where category is not null")
    assert len(rows) == 5
    for case, missing, completeness in rows:
        assert sorted(missing) == labels[case]["missing_required_evidence"], case
        assert (completeness == 1.0) == (not missing)
    gaps = dict(((r[0], r[1]), r[2]) for r in wh.query("select category, missing_evidence, packets from mart_evidence_gaps"))
    assert gaps == {("fraud", "3ds authentication"): 1, ("not_received", "proof of delivery"): 1}
    assert wh.query("select count(*) from mart_dispute_win_rate")[0][0] >= 3
