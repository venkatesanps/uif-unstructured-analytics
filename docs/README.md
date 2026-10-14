# UIF reference notes

Everything decided, built, measured and learned while creating UIF, the unstructured-data analytics
framework for merchant services. Start here.

| Doc | Read it when you want to know |
| --- | --- |
| [01 Design](01-design.md) | What the framework is, how it's layered, the data model, the agent roster |
| [02 Build log](02-build-log.md) | What was built in each step, in order, with the commit for each |
| [03 Results](03-results.md) | Every evaluation run, its numbers, and how much to trust them |
| [04 Runbooks](04-runbooks.md) | How to run it at work (Claude Code / Copilot), in AWS (Bedrock), and day to day |
| [05 Decisions and lessons](05-decisions-and-lessons.md) | Why things are the way they are, and every bug the tests caught |
| [06 Work environment](06-work-environment.md) | Firm constraints: LLM access, data handling, getting code onto the work network |
| [07 Open items](07-open-items.md) | What's left before each gate, and suggested next steps |

Other references in the repo root:

- `README.md`: quick start, format matrix, result tables
- `CLAUDE.md`: operating rules for coding agents (Claude Code; Copilot reads `.github/copilot-instructions.md`)
- `AGENT_EXTRACT.md`: protocol for an agent answering handoff requests
- `PARITY.md`: runbook for the local-agent vs Bedrock parity check (Gate C evidence)
- `LESSONS_LEARNED.md`: one line per lesson, newest first
- `infra/README.md`: AWS resources and IAM boundaries for Phase 2
- `data/README.md`: what the reference data is (and isn't)

Original design doc (Claude Docs, private to your account):
https://claude.ai/code/artifact/f6d68e3e-d9ac-47af-8aff-95d0e897a739

*Notes current as of 2026-10-13, repository head after the audio work (`01f7763`) plus these docs.*
