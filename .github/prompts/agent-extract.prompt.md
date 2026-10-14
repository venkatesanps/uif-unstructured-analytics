---
description: Act as UIF's extraction model - answer pending handoff requests per AGENT_EXTRACT.md
---

Follow #file:../../AGENT_EXTRACT.md exactly.

1. Run `uif handoff status` in the terminal to list pending requests.
2. For each request file under `.uif/store/handoff/requests/`, read it and write the response JSON to
   `.uif/store/handoff/responses/<request_id>.json`. Set `"agent"` to `copilot/<model name>`.
3. Do not open `raw/`, `restricted/`, `synthetic/`, `data/` or the database while doing this.
4. Run `uif handoff check` after every 5 responses and fix any problems it reports.
5. When all are answered, rerun the pipeline with `--llm handoff --force` and summarize what was
   auto-accepted and what went to review.
