"""AWS wiring tested locally with moto: S3 store, Snowpipe staging warehouse, and the
Lambda handler driving every step from an S3 'Object Created' event.
Textract/Comprehend/Bedrock are swapped for local adapters here; their own adapters are
covered by contract tests with stub clients and by the dev-account smoke run."""

import json

import pytest

moto = pytest.importorskip("moto")
boto3 = pytest.importorskip("boto3")

pytestmark = pytest.mark.aws
BUCKET = "uif-test"


@pytest.fixture
def aws_ctx(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("UIF_BUCKET", BUCKET)
    monkeypatch.setenv("UIF_TOKEN_SALT", "test-salt")
    monkeypatch.setenv("UIF_BEDROCK_MODEL_ID", "unused")
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        from uif.context import Context

        ctx = Context.from_config("aws", {"ocr.kind": "local", "guard.kind": "regex", "llm.kind": "rules"})
        yield ctx


def test_s3_store_roundtrip(aws_ctx):
    s = aws_ctx.store
    uri = s.put_bytes("a/b.json", b"{}")
    assert uri == f"s3://{BUCKET}/uif/a/b.json"
    assert s.get_bytes("a/b.json") == b"{}" and s.exists("a/b.json") and not s.exists("nope")
    assert s.list("a/") == ["a/b.json"]


def test_handler_runs_the_whole_pipeline_from_an_s3_event(aws_ctx, golden_dir):
    from uif import aws_handler
    from uif.steps import PIPELINE

    aws_handler._CTX = aws_ctx
    key = "landing/merchant/onboarding_portal/statement_01_B.pdf"
    boto3.client("s3").put_object(Bucket=BUCKET, Key=key,
                                  Body=(golden_dir / "merchant" / "statement_01_B.pdf").read_bytes())
    event = {"detail": {"bucket": {"name": BUCKET}, "object": {"key": key}}}
    first = aws_handler.handler(event)
    assert first["ok"] and not first["duplicate"]
    for name, _ in PIPELINE:
        res = aws_handler.handler({"step": name, "doc_id": first["doc_id"]})
        assert res["ok"], res

    published = [k for k in aws_ctx.store.list("publish/") if "extracted_fact" in k]
    assert published
    rows = [json.loads(l) for l in aws_ctx.store.get_bytes(published[0]).decode().splitlines()]
    assert {r["field_path"] for r in rows} >= {"gross_volume", "statement_period", "mid"}
    for k in aws_ctx.store.list(""):
        if not k.startswith(("raw/", "restricted/")):
            assert b"4111" not in aws_ctx.store.get_bytes(k).replace(b" ", b""), k

    again = aws_handler.handler(event)
    assert again["duplicate"]
