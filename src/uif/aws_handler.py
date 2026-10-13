"""AWS entry points. One handler, dispatched by step name, so every Step Functions
task state invokes the same image with {"step": ..., "doc_id": ...}.

Intake is triggered by an S3 object landing at
  landing/<source_group>/<source_system>/<file name>
(EventBridge "Object Created" event), and returns the doc_id the workflow carries."""

from __future__ import annotations

import os
import urllib.parse

from uif.context import Context
from uif.steps import STEPS, intake

_CTX: Context | None = None


def _ctx() -> Context:
    global _CTX
    if _CTX is None:  # reused across warm invocations
        _CTX = Context.from_config(os.environ.get("RUNTIME", "aws"))
    return _CTX


def _intake_from_s3(event: dict) -> dict:
    import boto3

    detail = event["detail"]
    bucket = detail["bucket"]["name"]
    key = urllib.parse.unquote_plus(detail["object"]["key"])
    parts = key.split("/")
    if len(parts) < 4 or parts[0] != "landing":
        raise ValueError(f"unexpected landing key {key}")
    source_group, source_system, file_name = parts[1], parts[2], parts[-1]
    body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    res = intake.run(_ctx(), body, file_name, source_group, source_system, submitter=detail.get("requester"))
    return res.model_dump() | {"duplicate": res.detail == "duplicate"}


def handler(event: dict, _context=None) -> dict:
    step = event.get("step", "intake")
    if step == "intake":
        return _intake_from_s3(event)
    if step not in STEPS:
        raise ValueError(f"unknown step {step}")
    res = STEPS[step](_ctx(), event["doc_id"])
    if not res.ok and not res.halt:
        raise RuntimeError(f"{step} failed: {res.detail}")  # let Step Functions retry
    return res.model_dump()
