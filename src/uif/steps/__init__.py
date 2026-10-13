"""Pipeline steps in execution order. Each takes (ctx, doc_id) and returns a StepResult,
so the local runner, a Lambda handler and a Step Functions task all call them the same way."""

from uif.steps import classify, extract, guard, intake, normalize, publish, resolve, validate

PIPELINE = [
    ("normalize", normalize.run),
    ("guard", guard.run),
    ("classify", classify.run),
    ("extract", extract.run),
    ("resolve", resolve.run),
    ("validate", validate.run),
    ("publish", publish.run),
]

STEPS = dict(PIPELINE)

__all__ = ["PIPELINE", "STEPS", "intake"]
