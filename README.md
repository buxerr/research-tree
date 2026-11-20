# Research Tree

Research Tree is a local, provider-agnostic CLI for exploring a research question through independent branches. Investigator agents explore different angles, an independent judge scores each checkpoint, low-value branches are pruned after bounded retries, and useful branches split into fresh follow-up investigations.

It is designed for market research and other evidence-led investigations. It stores the full local run history so you can inspect what passed, what was pruned, and why.

## What it does

- Starts several investigator branches with different research angles.
- Adds randomized association tokens to each investigator prompt. The default is 18% of prompt characters, an estimate because tokenizers differ by provider. Set the ratio to `0` to turn this off.
- Calls a judge in a separate, fresh process at every checkpoint. The judge can use the same provider as the investigators or a different provider/model.
- Scores usefulness from 0–100. `strictness` controls the pass threshold; higher strictness requires a higher score.
- Retries rejected branches up to a configured attempt limit, then prunes them while retaining their findings and checkpoint outputs.
- Splits useful branches into two or more children with new randomized contexts.
- Enforces limits for calls, nodes, depth, retries, and parallel branches.
- Saves prompts, raw responses, parsed results, judge decisions, run state, and a Markdown report locally.

Random associations are ideation prompts only. They do not count as evidence, and their effect on research quality is unproven. The judge is instructed to ignore them as evidence.

## Install

Requirements: Python 3.11 or newer, plus a supported local agent CLI. The default provider uses Codex CLI. Claude Code is shown as an optional provider. Research Tree has no runtime Python dependencies.

From a clone of this repository:

```powershell
python -m pip install -e .
python -m research_tree init
```

The `init` command creates `research-tree.toml` and adds `.research-tree/` to `.gitignore`. Edit the configuration to select available provider commands and adjust limits.

To install the reusable Codex skill into your user skill directory:

```powershell
.\scripts\install-codex-skill.ps1
```

## Run a research tree

```powershell
python -m research_tree run "Which Android app workflows have clear U.S. demand and weak direct competition?"
python -m research_tree list
python -m research_tree tree
python -m research_tree report
```

Each run prints its ID and report path. Pass a run ID to inspect an older run:

```powershell
python -m research_tree tree 20261120-143000-a1b2c3
python -m research_tree report 20261120-143000-a1b2c3
```

If the call budget is reached, increase `tree.max_calls` in `research-tree.toml` and resume:

```powershell
python -m research_tree resume 20261120-143000-a1b2c3
```

You can select a different configured judge at run time:

```powershell
python -m research_tree run "Research question" --provider codex --judge-provider claude
```

Use `python -m research_tree --help` and `python -m research_tree <command> --help` for the command reference. The `research-tree` executable is also installed; add your Python user `Scripts` folder to `PATH` to call it without `python -m`.

## Configure the tree

`python -m research_tree init` creates this configuration (also available as [`research-tree.toml.example`](research-tree.toml.example)):

| Setting | Default | Meaning |
|---|---:|---|
| `initial_branches` | 3 | Number of different angles to investigate first |
| `children_per_branch` | 2 | Number of fresh child branches after a useful checkpoint; minimum is 2 |
| `max_depth` | 2 | Number of splits below the initial branches |
| `max_attempts_per_branch` | 3 | Attempts before a failing branch is pruned |
| `max_nodes` | 25 | Maximum total branches in one run, including pruned branches |
| `max_calls` | 60 | Maximum investigator plus judge provider calls |
| `parallelism` | 3 | Number of branches processed concurrently |
| `strictness` | 0.55 | Pass threshold control from 0 (lenient) to 1 (strict) |
| `random_context_ratio` | 0.18 | Approximate fraction of each investigator prompt for random association payloads |
| `seed` | empty | Optional deterministic payload generation for the same question and branch angles |

The checkpoint score threshold is `30 + strictness × 60`, rounded to the nearest integer. The judge evaluates source quality, relevance, novelty, and usefulness. A model score is a triage signal, not a factual guarantee; inspect the cited evidence.

Provider commands are argument arrays, never shell command strings. Supported placeholders are `{prompt}`, `{output}`, and `{cwd}`. Configure `prompt_transport` as `stdin` or `argument`. Provider commands run as your user and may incur model/API charges. Use only commands you trust.

To use a distinct investigator and judge CLI, configure both provider tables and set their names:

```toml
[providers]
default = "codex"
judge = "claude"
```

The included Codex provider runs ephemeral and read-only. The included Claude Code example uses `claude -p`; adjust it to match the CLI and model installed on your machine.

## Local run data

Runs live under `.research-tree/runs/<run-id>/`:

```text
run.json
report.md
branches/<branch-id>/attempt-01/
  research-prompt.md
  research.md
  research.json
  judge-prompt.md
  judge.md
  checkpoint.json
```

Pruned branches keep their findings and judge feedback. The report shows accepted findings separately from findings found in branches that did not pass. Keep run data local unless you deliberately choose to share it; it may contain research questions, prompts, and model responses.

## Research limits

- Random payload ratio is measured by character count, not exact model tokens.
- The quality effect of random context has not been established. It can consume context and cost without improving results.
- Research quality depends on the provider’s available browsing, MCP tools, source access, and model. Research Tree itself does not provide a search index.
- The judge is another fresh invocation, not a guarantee of true independence if it uses the same model and provider as the investigator.
- Web keyword estimates are not app-store search counts. Preserve source links and label estimates and inference.
- A passing branch means “worth further exploration under this scoring rule,” not “validated market” or “go build.”

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the run lifecycle, persistence model, and judge criteria.

## License

MIT. See [`LICENSE`](LICENSE).
