"""Every step's output parses into its contract, both model-backed providers produce the
same shape, and the Step Functions definition runs the same steps in the same order."""

import json
import re
from pathlib import Path

from uif.contracts import (
    Classification,
    DocEnvelope,
    EntityLink,
    Extraction,
    GuardedDoc,
    NormalizedDoc,
    Validated,
)
from uif.providers.aws import BedrockLLM
from uif.providers.llm_common import response_schema
from uif.runner import process_bytes
from uif.steps import PIPELINE

ROOT = Path(__file__).resolve().parents[2]
MODELS = {"envelope": DocEnvelope, "normalized": NormalizedDoc, "guarded": GuardedDoc,
          "classification": Classification, "extraction": Extraction, "entity": EntityLink,
          "validated": Validated}


def test_every_step_output_matches_its_contract(ctx, golden_dir):
    f = golden_dir / "merchant" / "statement_00_A.pdf"
    run = process_bytes(ctx, f.read_bytes(), f.name, "merchant", "test")
    assert run.ok, [r for r in run.results if not r.ok]
    for kind, model in MODELS.items():
        model.model_validate_json(ctx.store.get_bytes(ctx.key(kind, doc_id=run.doc_id)))


def test_no_model_facing_artifact_lives_under_restricted(ctx, golden_dir):
    f = golden_dir / "merchant" / "statement_01_B.pdf"  # has a planted card number
    run = process_bytes(ctx, f.read_bytes(), f.name, "merchant", "test")
    guarded = ctx.get_model("guarded", GuardedDoc, doc_id=run.doc_id)
    assert any(x.kind == "pan" for x in guarded.findings)
    assert "4111" not in " ".join(p.text for p in guarded.pages)


def test_response_schema_requires_evidence_for_every_field(ctx):
    for name in ctx.registry.names():
        schema = response_schema(ctx.registry.get(name))
        assert set(schema["required"]) == set(ctx.registry.get(name).fields)
        for prop in schema["properties"].values():
            assert prop["required"] == ["value", "page", "quote", "confidence"]


class _FakeBedrock:
    def __init__(self, tool_input):
        self.tool_input, self.calls = tool_input, []

    def converse(self, **kw):
        self.calls.append(kw)
        return {"output": {"message": {"content": [{"toolUse": {"name": "x", "input": self.tool_input}}]}},
                "usage": {"inputTokens": 1200, "outputTokens": 300}}


def test_bedrock_adapter_forces_tool_and_coerces_shape(ctx):
    dt = ctx.registry.get("processor_statement")
    fake = _FakeBedrock({"gross_volume": {"value": 10.5, "page": 1, "quote": "Gross Sales $10.50",
                                          "confidence": 0.97}, "bogus_field": {"value": 1}})
    out = BedrockLLM("test-model", client=fake).extract([], dt)
    call = fake.calls[0]
    assert call["toolConfig"]["toolChoice"] == {"tool": {"name": "record_extraction"}}
    assert call["inferenceConfig"]["temperature"] == 0
    assert set(out.fields) == set(dt.fields)          # unknown keys dropped, missing ones filled
    assert out.fields["gross_volume"]["value"] == 10.5
    assert out.fields["mid"] == {"value": None, "page": None, "quote": None, "confidence": 0.0}
    assert out.usage.tokens_in == 1200


def test_state_machine_runs_pipeline_steps_in_order():
    raw = (ROOT / "orchestrator" / "statemachine.asl.json").read_text()
    raw = re.sub(r"\$\{(PrivateSubnets|SecurityGroups)\}", "[]", raw)
    asl = json.loads(raw)
    order, state = [], asl["StartAt"]
    while state:
        s = asl["States"][state]
        payload = s.get("Parameters", {}).get("Payload", {})
        cmd = s.get("Parameters", {}).get("Overrides", {}).get("ContainerOverrides", [{}])[0].get("Command", [])
        step = payload.get("step") or (cmd[-1] if cmd else None)
        if step and step != "intake":
            order.append(step)
        state = s.get("Next") or s.get("Default")
    assert order == [name for name, _ in PIPELINE]
