---
name: research-tree
description: Use Research Tree to investigate a market or other research question with branching local investigator agents, independent checkpoint judges, bounded retries, pruning, and saved findings. Use when the user asks to run or inspect a Research Tree study.
---

# Research Tree

Use the local `research-tree` CLI to run the user's research question through the configured project. The CLI handles branch creation, randomized ideation context, fresh judge invocations, retries, pruning, persistence, and report generation.

## Workflow

1. Find the project directory containing `research-tree.toml`. If none exists in the intended workspace, initialize that workspace with `python -m research_tree init` and review the generated provider configuration.
2. Run the user's question as written, adding only practical scope already established by the conversation (such as geography, audience, date, or budget).
3. If the run reaches its call budget, show the saved tree and report first. Increase `tree.max_calls` only when the user has asked for broader continuation, then resume the same run.
4. Inspect the saved `report.md` and relevant branch attempt artifacts. Summarize surviving leads, rejected branches, score thresholds, evidence links, and uncertainty.
5. Keep all claims traceable to saved sources. Clearly distinguish source-backed facts, third-party estimates, and inference.

## Evidence and seed handling

- Random association payloads are ideation prompts only. Never cite or treat them as evidence.
- A passing judge score means a branch is worth more investigation under that run's rule. It does not validate demand, product-market fit, or a decision to build.
- The configured provider determines whether live browsing and research tools are available. If a source was not checked, say so.
- Preserve uncertainty, contradictory findings, and pruned-branch insights in the user-facing summary.
- Do not publish local run data unless the user asks; it may contain prompts, research questions, and provider responses.

## Useful commands

```powershell
python -m research_tree run "<research question>"
python -m research_tree list
python -m research_tree tree [run-id]
python -m research_tree report [run-id]
python -m research_tree resume <run-id>
```
