"""Step 1: land the raw bytes, hash, dedupe, write the envelope."""

from __future__ import annotations

import hashlib
from pathlib import Path

from uif.context import Context
from uif.contracts import DocEnvelope, SourceGroup, StepResult
from uif.providers.formats import guess_mime  # noqa: F401  (re-exported)


def run(ctx: Context, data: bytes, file_name: str, source_group: str, source_system: str,
        submitter: str | None = None) -> StepResult:
    sha = hashlib.sha256(data).hexdigest()
    doc_id = sha[:20]
    env_key = ctx.key("envelope", doc_id=doc_id)
    if ctx.store.exists(env_key):
        return StepResult(doc_id=doc_id, step="intake", ok=True, output_key=env_key, detail="duplicate")
    raw_key = ctx.key("raw", doc_id=doc_id, file_name=Path(file_name).name)
    uri = ctx.store.put_bytes(raw_key, data)
    env = DocEnvelope(
        doc_id=doc_id,
        content_sha256=sha,
        source_group=SourceGroup(source_group),
        source_system=source_system,
        submitter=submitter,
        file_name=Path(file_name).name,
        mime_type=guess_mime(file_name),
        storage_uri=uri,
    )
    ctx.put_model("envelope", env, doc_id=doc_id)
    return StepResult(doc_id=doc_id, step="intake", ok=True, output_key=env_key)
