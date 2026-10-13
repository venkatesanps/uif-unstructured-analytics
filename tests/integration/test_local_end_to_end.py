"""Drop the golden set in, assert analytics come out of DuckDB, and re-runs are idempotent."""

from uif.runner import process_path


def test_marts_are_populated(processed):
    c, _ = processed
    wh = c.providers.warehouse
    rows = wh.query("select merchant_id, gross_volume, chargeback_ratio_pct, effective_rate_pct "
                    "from mart_underwriting_variance where gross_volume is not null")
    assert len(rows) >= 5
    assert all(r[2] is not None and 0 <= r[2] < 5 for r in rows)
    assert all(2.0 <= r[3] <= 3.5 for r in rows)
    themes = wh.query("select theme, count(*) from mart_analyst_themes group by 1")
    assert themes
    quality = dict((r[0], r[1]) for r in wh.query("select doc_type, docs from mart_pipeline_quality"))
    assert quality.get("processor_statement", 0) >= 5 and quality.get("risk_analyst_note", 0) >= 5


def test_review_queue_has_the_expected_items(processed):
    c, _ = processed
    reasons = [r[0] for r in c.providers.warehouse.query("select reason from v_review_queue")]
    assert "unknown_doc_type" in reasons
    assert "unresolved_merchant" in reasons
    assert any(r.startswith("missing_required") for r in reasons)


def test_reprocessing_is_idempotent(processed, golden_dir):
    c, _ = processed
    wh = c.providers.warehouse
    before = wh.query("select count(*) from extracted_fact")[0][0]
    process_path(c, golden_dir / "merchant", "merchant", "golden", force=True)
    assert wh.query("select count(*) from extracted_fact")[0][0] == before


def test_duplicate_upload_is_skipped(processed, golden_dir):
    c, _ = processed
    runs = process_path(c, golden_dir / "internal", "internal", "golden")
    assert all(r.results[0].detail == "duplicate" and len(r.results) == 1 for r in runs)
