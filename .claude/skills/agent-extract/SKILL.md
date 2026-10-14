---
name: agent-extract
description: Act as UIF's extraction model in handoff mode - answer pending extraction/classification requests from tokenized request files and write schema-shaped responses. Use when `uif run --llm handoff` reports documents waiting for an agent, or the user asks to "fill the handoff requests".
---

# Agent extraction (Claude Code)

Follow `AGENT_EXTRACT.md` at the repo root exactly. It is the shared protocol for Claude Code and
Copilot. Claude Code specifics:

- Find work with `.venv/bin/uif handoff status`. Open each listed request with the Read tool.
- Stay inside `.uif/store/handoff/`. Do not Read, Grep or Glob `raw/`, `restricted/`, `synthetic/`,
  `data/` or the DuckDB file while doing this task. If a request seems to need more context, answer
  null for that field rather than looking elsewhere.
- Write each response with the Write tool to `.uif/store/handoff/responses/<request_id>.json`.
  Set `"agent"` to `claude-code/<model>`.
- After each batch of about 5, run `.venv/bin/uif handoff check`.
- When done, run `.venv/bin/uif run <folder> --source <group> --llm handoff --force` for each folder
  (or `make run LLM=handoff` with `--force`), then report how many facts were auto-accepted versus
  sent to review. For golden runs, also run `.venv/bin/uif eval synthetic --llm handoff --no-run` and
  report the headline metrics.

Use the `pii-auditor` subagent afterwards if any response quotes something that looks like an
un-tokenized identifier.
