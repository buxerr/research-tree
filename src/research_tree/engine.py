from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any
from urllib.parse import quote, urlsplit

from .config import ProjectConfig
from .models import BranchNode, JudgeResult, ResearchResult, new_id
from .prompts import build_judge_prompt, build_research_prompt, parse_judge, parse_research
from .provider import CommandProvider, ProviderError
from .storage import write_run


@dataclass
class BranchOutcome:
    node: BranchNode
    child_angles: list[str]
    findings: list[dict[str, Any]]
    budget_exhausted: bool = False
    error: str = ""


class CallBudget:
    """Reserve researcher+judge calls atomically across parallel branches."""

    def __init__(self, config: ProjectConfig, run_dir: Path, state: dict[str, Any]):
        self.limit = config.tree.max_calls
        self.run_dir = run_dir
        self.state = state
        self.lock = threading.Lock()
        self.reserved = 0

    def reserve_checkpoint(self) -> bool:
        with self.lock:
            used = int(self.state.get("calls_used", 0))
            if used + self.reserved + 2 > self.limit:
                return False
            self.reserved += 2
            return True

    def activate_call(self) -> None:
        with self.lock:
            if self.reserved < 1:
                raise RuntimeError("Internal call budget reservation was lost.")
            self.reserved -= 1
            self.state["calls_used"] = int(self.state.get("calls_used", 0)) + 1
            write_run(self.run_dir, self.state)

    def release_reserved(self, count: int = 1) -> None:
        with self.lock:
            self.reserved = max(0, self.reserved - count)
            write_run(self.run_dir, self.state)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_branch(
    config: ProjectConfig,
    run_dir: Path,
    state: dict[str, Any],
    node_dict: dict[str, Any],
    provider: CommandProvider,
    judge_provider: CommandProvider,
    budget: CallBudget,
) -> BranchOutcome:
    node = BranchNode.from_dict(node_dict)
    findings: list[dict[str, Any]] = []
    child_angles: list[str] = []
    threshold = config.tree.score_threshold

    for attempt in range(node.attempts + 1, config.tree.max_attempts_per_branch + 1):
        if not budget.reserve_checkpoint():
            node.status = "pending"
            node.note = "Waiting for two model calls at the current call budget."
            return BranchOutcome(node=node, child_angles=[], findings=findings, budget_exhausted=True)

        node.attempts = attempt
        attempt_dir = run_dir / "branches" / node.id / f"attempt-{attempt:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        research_prompt, estimated_ratio = build_research_prompt(config, state, node, attempt)
        _write_text(attempt_dir / "research-prompt.md", research_prompt)
        record: dict[str, Any] = {
            "attempt": attempt,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "random_context_ratio_estimate": round(estimated_ratio, 4),
        }

        try:
            budget.activate_call()
            research_raw = provider.complete(research_prompt, run_dir)
        except (ProviderError, OSError) as exc:
            budget.release_reserved(1)
            message = str(exc)
            _write_text(attempt_dir / "research-error.md", message)
            record.update({"score": 0, "useful": False, "error": message})
            record["reasons"] = ["Investigator failed before producing a checkpointable result."]
            record["gaps"] = ["Check the provider CLI, credentials, and configured command."]
            node.checkpoints.append(record)
            _write_json(attempt_dir / "checkpoint.json", record)
            node.rejection_feedback = record["reasons"] + record["gaps"]
            continue

        _write_text(attempt_dir / "research.md", research_raw)
        research = parse_research(research_raw)
        _write_json(attempt_dir / "research.json", {
            "summary": research.summary,
            "findings": research.findings,
            "uncertainties": research.uncertainties,
            "child_angles": research.child_angles,
        })
        for item in research.findings:
            findings.append({"branch_id": node.id, "attempt": attempt, "finding": item, "accepted": False})

        judge_prompt = build_judge_prompt(
            question=node.question,
            node=node,
            attempt=attempt,
            research=research,
            threshold=threshold,
            previous_feedback=node.rejection_feedback,
        )
        _write_text(attempt_dir / "judge-prompt.md", judge_prompt)
        try:
            budget.activate_call()
            judge_raw = judge_provider.complete(judge_prompt, run_dir)
            judge = parse_judge(judge_raw)
            _write_text(attempt_dir / "judge.md", judge_raw)
        except (ProviderError, OSError) as exc:
            judge = JudgeResult(
                score=0,
                reasons=["Independent judge failed; the branch was conservatively rejected."],
                gaps=[str(exc)],
                raw="",
            )
            _write_text(attempt_dir / "judge-error.md", str(exc))

        useful = judge.score >= threshold
        record.update({
            "score": judge.score,
            "threshold": threshold,
            "useful": useful,
            "reasons": judge.reasons,
            "gaps": judge.gaps,
            "next_direction": judge.next_direction,
            "summary": research.summary,
        })
        node.checkpoints.append(record)
        _write_json(attempt_dir / "checkpoint.json", record)
        node.last_score = judge.score
        node.summary = research.summary
        if useful:
            node.status = "useful"
            node.accepted_findings = research.findings
            node.rejection_feedback = []
            node.note = "Passed an independent checkpoint."
            child_angles = research.child_angles[:]
            if judge.next_direction and judge.next_direction not in child_angles:
                child_angles.append(judge.next_direction)
            for entry in findings:
                entry["accepted"] = True
            return BranchOutcome(node=node, child_angles=child_angles, findings=findings)

        node.rejection_feedback = (judge.reasons + judge.gaps)[:12]

    node.status = "pruned"
    node.note = f"Pruned after {node.attempts} attempt(s); all checkpoint outputs and findings were retained."
    return BranchOutcome(node=node, child_angles=[], findings=findings)


def _new_child(
    question: str,
    parent: BranchNode,
    angle: str,
) -> BranchNode:
    return BranchNode(
        id=new_id(),
        question=question,
        angle=angle,
        depth=parent.depth + 1,
        parent_id=parent.id,
    )


def write_report(run_dir: Path, state: dict[str, Any]) -> Path:
    lines = [
        f"# Research Tree: {state['question']}",
        "",
        f"- **Run:** `{state['id']}`",
        f"- **Status:** {state['status']}",
        f"- **Provider:** `{state.get('provider', 'unknown')}`",
        f"- **Judge provider:** `{state.get('judge_provider', state.get('provider', 'unknown'))}`",
        f"- **Model calls used:** {state.get('calls_used', 0)}",
        f"- **Created:** {state['created_at']}",
        "",
        "> Randomized associations are ideation prompts only. They are not evidence. Context ratio is estimated from character counts because provider tokenizers differ.",
        "",
        "## Branches",
        "",
    ]

    def render_node(node_id: str, indent: int = 0) -> None:
        node = state["nodes"][node_id]
        pad = "  " * indent
        score = f"; score {node['last_score']}/100" if node.get("last_score") is not None else ""
        lines.append(f"{pad}- **{node['id']} — {node['status']}**{score}: {node['angle']}")
        if node.get("summary"):
            lines.append(f"{pad}  - {node['summary']}")
        if node.get("note"):
            lines.append(f"{pad}  - {node['note']}")
        if node.get("accepted_findings"):
            for finding in node["accepted_findings"]:
                claim = finding.get("claim", json.dumps(finding, ensure_ascii=False)) if isinstance(finding, dict) else str(finding)
                lines.append(f"{pad}  - Finding: {claim}")
        for checkpoint in node.get("checkpoints", []):
            lines.append(
                f"{pad}  - Checkpoint {checkpoint.get('attempt')}: "
                f"{checkpoint.get('score', 0)}/100; "
                f"{'passed' if checkpoint.get('useful') else 'rejected'}"
            )
            for reason in checkpoint.get("reasons", []):
                lines.append(f"{pad}    - Judge: {reason}")
            for gap in checkpoint.get("gaps", []):
                lines.append(f"{pad}    - Gap: {gap}")
        for child_id in node.get("children", []):
            render_node(child_id, indent + 1)

    for root_id in state.get("root_ids", []):
        render_node(root_id)

    lines.extend(["", "## Saved findings", ""])
    if not state.get("findings"):
        lines.append("No structured findings were returned yet.")
    else:
        for item in state["findings"]:
            finding = item.get("finding", {})
            claim = finding.get("claim", json.dumps(finding, ensure_ascii=False)) if isinstance(finding, dict) else str(finding)
            label = "accepted" if item.get("accepted") else "checkpoint/pruned"
            lines.append(f"- **{label} · {item.get('branch_id')} · attempt {item.get('attempt')}:** {claim}")
            if isinstance(finding, dict):
                evidence = finding.get("evidence")
                if evidence:
                    lines.append(f"  - Evidence: {evidence}")
                for source in finding.get("sources", []) if isinstance(finding.get("sources", []), list) else []:
                    if isinstance(source, dict) and source.get("url"):
                        title = source.get("title") or source["url"]
                        url = str(source["url"])
                        if urlsplit(url).scheme.lower() in {"http", "https"}:
                            safe_url = quote(url, safe=":/?#[]@!$&'*,;=%")
                            safe_title = str(title).replace("[", "\\[").replace("]", "\\]")
                            lines.append(f"  - Source: [{safe_title}]({safe_url})")
                        else:
                            lines.append(f"  - Source (unlinked): {title} — {url}")

    lines.extend(["", "## Branch artifacts", ""])
    for node_id, node in state["nodes"].items():
        lines.append(f"- `{node_id}`: `branches/{node_id}/` ({node.get('attempts', 0)} attempt(s))")
    if state.get("error"):
        lines.extend(["", "## Run note", "", state["error"]])
    destination = run_dir / "report.md"
    _write_text(destination, "\n".join(lines))
    return destination


def execute_tree(
    config: ProjectConfig,
    run_dir: Path,
    state: dict[str, Any],
    provider: CommandProvider,
    judge_provider: CommandProvider,
) -> dict[str, Any]:
    state["status"] = "running"
    state["error"] = ""
    state["settings"] = {
        "initial_branches": config.tree.initial_branches,
        "children_per_branch": config.tree.children_per_branch,
        "max_depth": config.tree.max_depth,
        "max_attempts_per_branch": config.tree.max_attempts_per_branch,
        "max_nodes": config.tree.max_nodes,
        "max_calls": config.tree.max_calls,
        "parallelism": config.tree.parallelism,
        "strictness": config.tree.strictness,
        "score_threshold": config.tree.score_threshold,
        "random_context_ratio": config.tree.random_context_ratio,
    }
    for node in state["nodes"].values():
        if node.get("status") == "running":
            node["status"] = "pending"
    write_run(run_dir, state)
    budget = CallBudget(config, run_dir, state)
    provider_name = state.get("provider", config.default_provider)

    while True:
        pending = [
            item for item in state["nodes"].values()
            if item.get("status") == "pending"
            and int(item.get("attempts", 0)) < config.tree.max_attempts_per_branch
        ]
        exhausted_attempts = [
            item for item in state["nodes"].values()
            if item.get("status") == "pending"
            and int(item.get("attempts", 0)) >= config.tree.max_attempts_per_branch
        ]
        for item in exhausted_attempts:
            item["status"] = "pruned"
            item["note"] = "Attempt limit reached before a passing checkpoint."
        if exhausted_attempts:
            write_run(run_dir, state)
        if not pending:
            break

        for item in pending:
            item["status"] = "running"
        write_run(run_dir, state)
        outcomes: list[BranchOutcome] = []
        task_errors: list[str] = []
        with ThreadPoolExecutor(max_workers=config.tree.parallelism) as pool:
            futures = {
                pool.submit(
                    _run_branch,
                    config,
                    run_dir,
                    state,
                    item.copy(),
                    provider,
                    judge_provider,
                    budget,
                ): item["id"]
                for item in pending
            }
            for future in as_completed(futures):
                node_id = futures[future]
                try:
                    outcomes.append(future.result())
                except Exception as exc:  # Keep a failed branch resumable and preserve the rest of the run.
                    failed_node = BranchNode.from_dict(state["nodes"][node_id])
                    failed_node.status = "pending"
                    failed_node.note = f"Branch worker failed and can be resumed: {exc}"
                    outcomes.append(BranchOutcome(failed_node, [], [], error=str(exc)))
                    task_errors.append(f"{node_id}: {exc}")

        added_children = False
        budget_exhausted = False
        for outcome in outcomes:
            node = outcome.node
            state["nodes"][node.id] = node.to_dict()
            state["findings"].extend(outcome.findings)
            budget_exhausted = budget_exhausted or outcome.budget_exhausted
            if outcome.error:
                state["error"] = (state.get("error", "") + "\n" + outcome.error).strip()
            if node.status != "useful":
                continue

            remaining_slots = config.tree.max_nodes - len(state["nodes"])
            if node.depth >= config.tree.max_depth:
                node.status = "useful_leaf"
                node.note = "Useful branch kept at the configured depth limit."
            elif remaining_slots < 2:
                node.status = "useful_leaf"
                node.note = "Useful branch retained; the node budget left fewer than two slots for a split."
            else:
                split_count = min(config.tree.children_per_branch, remaining_slots)
                if split_count < 2:
                    node.status = "useful_leaf"
                    node.note = "Useful branch retained; the node budget did not allow a two-way split."
                else:
                    proposed = outcome.child_angles[:]
                    while len(proposed) < split_count:
                        proposed.append(f"Test a distinct implication of: {node.summary}")
                    seen: set[str] = set()
                    for index in range(split_count):
                        angle = proposed[index].strip() or f"Investigate follow-up {index + 1}."
                        if angle in seen:
                            angle = f"Independent follow-up {index + 1}: {angle}"
                        seen.add(angle)
                        child = _new_child(state["question"], node, angle)
                        state["nodes"][child.id] = child.to_dict()
                        node.children.append(child.id)
                    node.note = f"Passed checkpoint and split into {len(node.children)} child branches."
                    added_children = True
            state["nodes"][node.id] = node.to_dict()

        write_run(run_dir, state)
        if task_errors:
            state["status"] = "interrupted"
            state["error"] = "; ".join(task_errors)
            break
        if budget_exhausted or any(n.get("status") == "pending" for n in state["nodes"].values()):
            state["status"] = "budget_exhausted"
            state["error"] = (
                f"The run used {state.get('calls_used', 0)} calls; update tree.max_calls in research-tree.toml and resume."
            )
            break
        if not added_children:
            break

    if state["status"] == "running":
        state["status"] = "complete"
    write_run(run_dir, state)
    write_report(run_dir, state)
    return state
