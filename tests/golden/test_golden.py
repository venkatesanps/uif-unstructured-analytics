"""Golden-set gates. Same metrics and thresholds as `uif eval` and CI."""

from uif.evals import gate


def test_gates_pass_with_offline_baseline(processed):
    _, report = processed
    assert gate(report) == [], report


def test_planted_identifiers_never_leave_the_restricted_zone(processed):
    _, report = processed
    assert report["pii_leakage"] == 0, report["pii_leak_locations"]


def test_unseen_layout_goes_to_review_instead_of_guessing(processed):
    _, report = processed
    doc = next(d for d in report["documents_detail"] if d["file"].endswith("_C.pdf"))
    assert any(r.startswith("missing_required") for r in doc["review_tasks"])


def test_unknown_document_is_parked_for_the_schema_designer(processed):
    _, report = processed
    doc = next(d for d in report["documents_detail"] if d["file"].startswith("external/"))
    assert doc["doc_type"] == "unknown" and doc["review_tasks"] == ["unknown_doc_type"]


def test_merchant_not_in_master_is_flagged(processed):
    _, report = processed
    assert report["entity_accuracy"] == 1.0
    flagged = [d for d in report["documents_detail"] if "unresolved_merchant" in d.get("review_tasks", [])]
    assert len(flagged) >= 2
