# Bedrock parity runbook (Gate C evidence)

**Question:** do results from your local agent (Claude Code or Copilot, via handoff) predict what
Bedrock will do in production?

**Method:** both answer the *same* golden requests (same tokenized text, system prompt, user prompt
and schema). We diff the answers field by field and score each side against the golden labels by
replaying it through the real pipeline.

```
laptop                                   AWS dev account
------                                   ---------------
LLM=handoff make run  ──► requests       
agent answers them    ──► answers/claude-code
uif handoff export requests ──zip──►  S3: uif/handoff/inbox/golden-requests.zip
                                         ECS task: uif --runtime aws handoff answer --with bedrock
                                         S3: uif/handoff/outbox/bedrock-answers.zip
uif handoff import --to answers/bedrock ◄──zip──
uif parity diff --labels synthetic  ──►  parity report (markdown + JSON)
```

Only synthetic (or fully redacted) documents take part. The bundles hold guard-tokenized text,
`import` refuses any file the guard would still change, and real merchant documents never leave AWS.

## 1. Laptop: requests and agent answers

```bash
make synth
LLM=handoff make run                       # writes one request per document, parks them
# Claude Code: /agent-extract     (Copilot: the agent-extract prompt)
.venv/bin/uif handoff check
cp .uif/store/handoff/requests/*.json  evals/golden/requests/
cp .uif/store/handoff/responses/*.json evals/golden/answers/claude-code/
.venv/bin/uif handoff export requests --out golden-requests.zip
```

`evals/golden/` already holds a request set and Claude answers for the current generator. Redo
this step whenever the generator, guard, schemas or prompts change, because request IDs change with
them (`tests/contract/test_parity.py` fails when they drift).

## 2. AWS dev: Bedrock answers the same requests

Prerequisites: Bedrock model access enabled for the Claude model you'll use in production;
`UIF_BEDROCK_MODEL_ID` set to that model ID or inference profile; the task role allows
`bedrock:InvokeModel` on it and `s3:GetObject`/`PutObject` on `<prefix>/handoff/*`.

```bash
aws s3 cp golden-requests.zip s3://$UIF_BUCKET/uif/handoff/inbox/golden-requests.zip

aws ecs run-task --cluster <cluster> --launch-type FARGATE --task-definition <uif-task> \
  --network-configuration 'awsvpcConfiguration={subnets=[<private-subnet>],securityGroups=[<sg>],assignPublicIp=DISABLED}' \
  --overrides '{"containerOverrides":[{"name":"uif","command":[
      "python","-m","uif.cli","--runtime","aws","handoff","answer","--with","bedrock",
      "--bundle","store:handoff/inbox/golden-requests.zip",
      "--out","store:handoff/outbox/bedrock-answers.zip"]}]}'

aws s3 cp s3://$UIF_BUCKET/uif/handoff/outbox/bedrock-answers.zip .
```

Any shell in the dev account with the image installed and the same role works too
(`uif --runtime aws handoff answer ...`). The task exits non-zero if any request failed, and the
JSON summary names each failure. Adaptive retries handle Bedrock throttling.

## 3. Laptop: compare

```bash
.venv/bin/uif handoff import --path bedrock-answers.zip --to evals/golden/answers/bedrock
.venv/bin/uif parity diff --labels synthetic --names claude-code,bedrock \
    --report evals/parity-report.md --json evals/parity-report.json
```

## Gate C criteria

| Check | Pass when |
| --- | --- |
| Coverage | Every request answered by both sides |
| Required-field agreement | ≥ 95% (`parity.PARITY_GATES`) |
| Both sides on golden labels | Both pass the standard gates (F1, grounding, leakage, injection) |
| Disagreements reviewed | Each one triaged in the report: Bedrock wrong / agent wrong / both acceptable |

When they disagree, fix the **prompt or schema** (so both sides get the improvement), regenerate
requests, and re-answer on both sides. Don't relax validator thresholds, and don't tune for one
side only.

## What parity does and doesn't tell you

- It tells you local agent runs are a fair proxy for Bedrock on these documents and prompts, so
  prompt and schema work done on the laptop carries over to production.
- It doesn't measure accuracy on real documents. That happens in AWS only: Bedrock on real documents,
  with reviewer decisions (`review_task`) as the labels, in shadow mode before anything goes downstream.
- Copilot may run a different model family. If you use it, run it as its own answer set
  (`answers/copilot`) and compare it with Bedrock separately.
