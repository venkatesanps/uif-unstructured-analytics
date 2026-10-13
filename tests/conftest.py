import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("UIF_HOME", str(ROOT))


@pytest.fixture(scope="session")
def golden_dir(tmp_path_factory) -> Path:
    from uif.synth import generate

    out = tmp_path_factory.mktemp("synthetic")
    generate(out, n=12, seed=7)
    return out


def make_ctx(tmp_path: Path, **overrides):
    from uif.context import Context

    base = {"store.root": str(tmp_path / "store"), "warehouse.path": str(tmp_path / "uif.duckdb"),
            "llm.kind": "rules"}
    base.update(overrides)
    return Context.from_config("local", base)


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


@pytest.fixture(scope="session")
def processed(tmp_path_factory, golden_dir):
    """Whole golden set run once through the local pipeline (rules extractor)."""
    from uif.evals import evaluate

    tmp = tmp_path_factory.mktemp("run")
    c = make_ctx(tmp)
    report = evaluate(c, golden_dir, run_pipeline=True)
    return c, report
