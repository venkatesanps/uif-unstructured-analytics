---
name: aws-deploy-check
description: Pre-deploy gate for the UIF AWS runtime - runs the moto AWS tests, validates the Step Functions definition, checks IAM/KMS boundaries in infra, then (only with explicit approval) deploys to the dev account. Use before any AWS deploy.
---

# AWS deploy check

1. `make ci` must be green (includes `tests/aws` under moto).
2. Validate `orchestrator/statemachine.asl.json`: substitute placeholders and run
   `aws stepfunctions validate-state-machine-definition` if the CLI and credentials are available;
   otherwise rely on `tests/contract` (step order) and say so.
3. Review infra (`infra/`) against the boundary rules and list any violation:
   - only the guard and normalize roles can read `raw/` and `restricted/`; they cannot call Bedrock
   - extract role can read `guarded/`, call Bedrock via VPC endpoint, nothing else
   - buckets: SSE-KMS, block public access, TLS-only policy; no public egress from tasks
4. Confirm `UIF_BEDROCK_MODEL_ID` points at the approved model and `UIF_TOKEN_SALT` comes from
   Secrets Manager, not plain env.
5. Ask the user before deploying. Deploy to **dev only**, then push the synthetic set to
   `landing/<group>/golden/` and compare published facts with the local run (`make eval` numbers).
6. Report: checks passed/failed, diffs between local and AWS results, anything skipped and why.
