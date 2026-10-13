"""Local orchestrator. Same step order and contracts as the Step Functions
definition in orchestrator/statemachine.asl.json."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from uif.context import Context
from uif.contracts import StepResult
from uif.steps import PIPELINE, intake


@dataclass
class DocRun:
    doc_id: str
    file_name: str
    results: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)


def process_bytes(ctx: Context, data: bytes, file_name: str, source_group: str, source_system: str,
                  submitter: str | None = None, force: bool = False) -> DocRun:
    first = intake.run(ctx, data, file_name, source_group, source_system, submitter)
    run = DocRun(first.doc_id, file_name, [first])
    if first.detail == "duplicate" and not force:
        return run
    for name, step in PIPELINE:
        try:
            res = step(ctx, first.doc_id)
        except Exception as exc:  # surface, don't hide: the step name and error go in the run record
            res = StepResult(doc_id=first.doc_id, step=name, ok=False, halt=True, detail=f"{type(exc).__name__}: {exc}")
        run.results.append(res)
        if res.halt:
            break
    return run


def process_path(ctx: Context, path: str | Path, source_group: str, source_system: str,
                 submitter: str | None = None, force: bool = False) -> list[DocRun]:
    path = Path(path)
    files = sorted(p for p in path.rglob("*") if p.is_file() and not p.name.endswith(".label.json")) \
        if path.is_dir() else [path]
    return [process_bytes(ctx, f.read_bytes(), f.name, source_group, source_system, submitter, force)
            for f in files]
