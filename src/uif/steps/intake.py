"""Step 1: land the raw bytes, hash, dedupe, write the envelope."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from uif.context import Context
from uif.contracts import DocEnvelope, SourceGroup, StepResult

_EXTRA_MIME = {".eml": "message/rfc822", ".msg": "application/vnd.ms-outlook", ".md": "text/markdown",
               ".csv": "text/csv", ".txt": "text/plain"}


def guess_mime(file_name: str) -> str:
    ext = Path(file_name).suffix.lower()
    return _EXTRA_MIME.get(ext) or mimetypes.guess_type(file_name)[0] or "application/octet-stream"


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
