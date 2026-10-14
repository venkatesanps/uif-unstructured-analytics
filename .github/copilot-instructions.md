# UIF repository instructions for Copilot

Follow `CLAUDE.md` in the repo root: it holds the operating rules for every coding agent here (guard
before model, evidence on every value, schema-first doc types, gates as the definition of done).

When asked to extract, answer handoff requests, or "act as the model", follow `AGENT_EXTRACT.md`. The
reusable prompt is `.github/prompts/agent-extract.prompt.md`.

Never open `raw/` or `restricted/` under the store, never paste document text into chat outside the
handoff files, and never use real merchant documents on a laptop.
