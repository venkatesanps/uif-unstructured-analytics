# 07 Open items

## Before Gate B is real (Phase 1)

- [ ] Get 5–10 **redacted real samples** per doc type and add them to a separate golden set.
- [ ] Run the golden set with **Claude Code at work** (handoff) and record an independent baseline
      (`evals/golden/answers/claude-code-work`).
- [ ] Make the golden set harder: more statement layouts, worse scans, multi-month statements, notes
      that rule a theme *out* ("no chargeback concerns").
- [ ] Run the `prompt-tuner` subagent against the work baseline.
- [ ] Add an LLM tiebreak to the entity resolver for near-miss merchant names.
- [ ] First dashboards on the marts (underwriting variance, analyst themes, evidence gaps, pipeline
      quality) plus a review-queue view.
- [ ] Replace `data/reference/reason_codes.csv` evidence requirements with the disputes team's list.

## Gate C (Phase 2: AWS dev)

- [ ] **Bedrock parity run** in the dev account (`PARITY.md`); triage every disagreement.
- [ ] IaC (CDK or Terraform per platform standard) from `infra/README.md`: buckets, KMS, IAM
      boundaries, EventBridge, Lambda, ECS, Step Functions, VPC endpoints.
- [ ] Execute `sql/snowflake/core.sql` in a dev schema; add MERGE tasks for the remaining tables
      (`snowflake-ddl` skill).
- [ ] Exercise Textract, Comprehend and Transcribe adapters for real (only stubs/mocks so far).
- [ ] Shadow mode on real documents; reviewer decisions become labels.
- [ ] Security, PCI and model-risk sign-off.

## Audio

- [ ] Measure real recognition: whisper.cpp on the Mac (`brew install whisper-cpp`, set
      `UIF_WHISPER_MODEL`) and regenerate samples with `say` voices; Transcribe in AWS dev.
- [ ] Propagate quality flags through containers (an audio file inside an email or ZIP currently loses
      its low-accuracy flag).

## Readers not yet built

- [ ] Outlook `.msg` (needs `extract-msg`), PowerPoint, RTF.

## Phase 3

- [ ] Signal Builder (typed risk signals into risk queues)
- [ ] Analyst Q&A agent (text-to-SQL over marts + retrieval with citations)
- [ ] Schema Designer (cluster `unknown` docs → draft schema + samples for approval)
- [ ] Embeddings + vector search (Cortex Search or OpenSearch)

## Housekeeping

- [ ] Decide repo visibility; optionally rewrite commit author email to the GitHub no-reply address.
- [ ] Wire `make ci` into the team's CI system (Bitbucket Pipelines or GitHub Actions).
