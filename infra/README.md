# Infra (Phase 2)

Phase 0 ships the runtime code, the container targets and the Step Functions definition. The IaC
(CDK or Terraform, whichever your platform team standardizes on) is a Phase 2 deliverable. It needs:

| Resource | Notes |
| --- | --- |
| S3 bucket `UIF_BUCKET` | SSE-KMS (`UIF_KMS_KEY_ID`), block public access, TLS-only bucket policy, EventBridge notifications on |
| Prefix boundaries | `raw/` + `restricted/` readable only by the normalize and guard roles; everything else by pipeline roles |
| EventBridge rule | `Object Created` on `landing/` → starts the state machine with the event |
| Lambda (image `--target lambda`) | One function, `RUNTIME=aws`; dispatches on `{"step": ...}` |
| ECS cluster + task def (image `--target task`) | Fargate, private subnets, no public IP; used by normalize and extract |
| Step Functions | `orchestrator/statemachine.asl.json`; substitute `${StepFunctionArn}`, `${ClusterArn}`, `${HeavyTaskDefArn}`, `${PrivateSubnets}`, `${SecurityGroups}` |
| VPC endpoints | S3, Textract, Comprehend, Bedrock runtime, Secrets Manager, CloudWatch Logs |
| Secrets Manager | `UIF_TOKEN_SALT` (injected as env from the secret) |
| Snowflake | Storage integration on `publish/`, `sql/snowflake/core.sql` (pipe, stream, MERGE tasks, masking) |

IAM sketch
- normalize role: read `raw/`, write `restricted/`, Textract.
- guard role: read `restricted/`, write `guarded/`, Comprehend. **No Bedrock.**
- extract role: read `guarded/`, `classification/`; write `extraction/`; `bedrock:InvokeModel` on the approved model only. **No access to `raw/` or `restricted/`.**
- publish role: read pipeline prefixes except `raw/` and `restricted/`; write `publish/`.
- parity task (dev only): read/write `handoff/`; `bedrock:InvokeModel` on the approved model. No other prefixes.

Smoke test after deploy: upload `synthetic/<group>/*` to `landing/<group>/golden/` and compare the
published NDJSON with the local `make eval` run (the `aws-deploy-check` skill does this).
