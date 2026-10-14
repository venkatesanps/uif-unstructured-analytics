# 06 Work environment

Constraints that shaped the design. Confirm each against current firm policy before relying on it.

## LLM access

| Where | Allowed | How UIF uses it |
| --- | --- | --- |
| Work laptop | Claude (Claude Code / Claude agents) and Copilot; no Ollama or local models | `--llm handoff` (agent answers request files), or `--llm anthropic` through an approved gateway if one exists |
| AWS | Bedrock only | `config/aws.yaml`: `llm.kind: bedrock`, `UIF_BEDROCK_MODEL_ID` set to the approved model or inference profile |

Prefer Claude Code over Copilot for local runs: Bedrock runs Claude, so Claude Code is the closer
preview. Every fact records which agent produced it.

## Data handling

- Laptops: synthetic or fully redacted documents only. Real merchant documents stay in AWS.
- Before real documents go through any agent or gateway, get the firm's data-handling approval for
  that tool and data class (approval is about tool + data, even though the agent only sees tokens).
- Real-document accuracy is measured in AWS: Bedrock + reviewer decisions as labels, shadow mode first.
- AML/SAR material is out of scope unless compliance approves a segregated deployment.
- Register the classifier/extractor under the firm's model risk process before production (Gate C).

## Getting code onto the work network

- Emailing the repo (even as 250 KB parts) was blocked: `550 5.0.0 JPMC.Attachment.Filter policy
  Violation`. That filter is a deliberate control; don't try to work around it.
- Current route: GitHub repo `venkatesanps/uif-unstructured-analytics`. Check that bringing external
  code onto the network is permitted. If the repo is private, you'll need to sign in to personal
  GitHub from work, which may be blocked.
- Alternatives: ask IT for the sanctioned transfer path (internal Bitbucket/GitHub import, secure file
  transfer, open-source intake), or rebuild inside the firm from the design using Claude/Copilot there.
- Commits are authored with the personal Gmail address; they can be rewritten to the GitHub no-reply
  address if the repo is public.
