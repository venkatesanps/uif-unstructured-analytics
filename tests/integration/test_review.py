import json

from uif.contracts import ReviewStatus, Validated
from uif.review import apply_decision, open_tasks
from uif.runner import process_bytes
from tests.adversarial.test_injection import _ObedientLLM


def test_correction_updates_fact_closes_task_and_feeds_golden_set(ctx, golden_dir, tmp_path):
    ctx.cfg["registry"]["path"] = str(tmp_path / "registry_copy")
    import shutil
    from uif.config import repo_root

    shutil.copytree(repo_root() / "registry", ctx.cfg["registry"]["path"])
    ctx.providers.llm = _ObedientLLM(0.0, "Total Gross Sales: $0.00")
    f = golden_dir / "merchant" / "statement_02_A.pdf"
    run = process_bytes(ctx, f.read_bytes(), f.name, "merchant", "test")

    task = next(t for t in open_tasks(ctx) if t["doc_id"] == run.doc_id and "not_grounded" in t["reason"])
    label = json.loads((golden_dir / "labels" / "statement_02_A.pdf.json").read_text())
    true_gross = label["fields"]["gross_volume"]
    result = apply_decision(ctx, task["task_id"], "corrected", "reviewer@test", true_gross)
    assert result["corrections_logged"] == 1

    val = ctx.get_model("validated", Validated, doc_id=run.doc_id)
    gross = next(x for x in val.facts if x.field_path == "gross_volume")
    assert gross.review_status == ReviewStatus.corrected and gross.value_norm == true_gross
    assert task["task_id"] not in {t["task_id"] for t in open_tasks(ctx)}
    log = (tmp_path / "registry_copy" / "doc_types" / "processor_statement" / "golden" / "corrections.jsonl")
    assert json.loads(log.read_text().splitlines()[-1])["corrected_value"] == true_gross
