from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .config import DEFAULT_CONFIG, ProjectConfig, load_config
from .engine import execute_tree, write_report
from .provider import CommandProvider
from .storage import create_run, latest_run_dir, list_runs, locate_run, read_run, write_run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-tree",
        description="Run evidence-led research through branching investigator and judge agents.",
    )
    parser.add_argument("-C", "--project", type=Path, default=Path.cwd(), help="project directory (default: current directory)")
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="create a local research-tree.toml")
    init_parser.add_argument("directory", nargs="?", type=Path, help="directory to initialize (default: --project)")
    init_parser.add_argument("--force", action="store_true", help="replace an existing research-tree.toml")

    run_parser = commands.add_parser("run", help="start a new research tree")
    run_parser.add_argument("question", nargs="+", help="research question")
    run_parser.add_argument("--provider", help="provider name from research-tree.toml")
    run_parser.add_argument("--judge-provider", help="independent checkpoint judge provider")

    resume_parser = commands.add_parser("resume", help="continue a paused or call-budget-limited run")
    resume_parser.add_argument("run_id", help="saved run ID")
    resume_parser.add_argument("--provider", help="override the run's provider")
    resume_parser.add_argument("--judge-provider", help="override the run's judge provider")

    for name, help_text in (
        ("tree", "show the branch structure"),
        ("report", "show the saved evidence-led report"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("run_id", nargs="?", help="run ID (default: latest run)")

    commands.add_parser("list", help="list saved runs")
    return parser


def _init(path: Path, force: bool) -> int:
    root = path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "research-tree.toml"
    if config_path.exists() and not force:
        print(f"Already initialized: {config_path}\nUse --force to replace it.", file=sys.stderr)
        return 2
    config_path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    ignore_path = root / ".gitignore"
    ignore_line = ".research-tree/"
    existing = ignore_path.read_text(encoding="utf-8") if ignore_path.exists() else ""
    if ignore_line not in existing.splitlines():
        suffix = "" if not existing or existing.endswith(("\n", "\r")) else "\n"
        ignore_path.write_text(existing + suffix + ignore_line + "\n", encoding="utf-8")
    print(f"Initialized local research project: {root}")
    print("Edit research-tree.toml, then run: python -m research_tree run \"your research question\"")
    return 0


def _select_provider(config: ProjectConfig, name: str | None) -> CommandProvider:
    selected = name or config.default_provider
    if selected not in config.providers:
        choices = ", ".join(sorted(config.providers)) or "(none configured)"
        raise ValueError(f"Provider {selected!r} is not configured. Available providers: {choices}")
    return CommandProvider(config.providers[selected])


def _format_tree(state: dict) -> str:
    lines = [f"Run {state['id']} — {state['status']} — {state.get('calls_used', 0)} calls"]

    def walk(node_id: str, depth: int) -> None:
        node = state["nodes"][node_id]
        score = f" score={node['last_score']}" if node.get("last_score") is not None else ""
        lines.append(
            f"{'  ' * depth}- {node_id} [{node['status']}; attempts={node.get('attempts', 0)}{score}] {node['angle']}"
        )
        if node.get("note"):
            lines.append(f"{'  ' * (depth + 1)}{node['note']}")
        for child_id in node.get("children", []):
            walk(child_id, depth + 1)

    for root_id in state.get("root_ids", []):
        walk(root_id, 0)
    return "\n".join(lines)


def _get_run(config: ProjectConfig, run_id: str | None) -> tuple[Path, dict]:
    run_dir = locate_run(config, run_id) if run_id else latest_run_dir(config)
    return run_dir, read_run(run_dir)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return _init(args.directory or args.project, args.force)

    try:
        config = load_config(args.project)
        if args.command == "run":
            question = " ".join(args.question).strip()
            if not question:
                raise ValueError("Research question cannot be empty.")
            provider_name = args.provider or config.default_provider
            judge_provider_name = args.judge_provider or config.default_judge_provider
            provider = _select_provider(config, provider_name)
            judge_provider = _select_provider(config, judge_provider_name)
            run_dir, state = create_run(
                config, question, provider_name, judge_provider_name
            )
            execute_tree(config, run_dir, state, provider, judge_provider)
            print(f"Run: {state['id']} ({state['status']})")
            print(f"Report: {run_dir / 'report.md'}")
            print(_format_tree(state))
            return 0

        if args.command == "resume":
            run_dir = locate_run(config, args.run_id)
            state = read_run(run_dir)
            provider_name = args.provider or state.get("provider") or config.default_provider
            judge_provider_name = (
                args.judge_provider or state.get("judge_provider") or config.default_judge_provider
            )
            provider = _select_provider(config, provider_name)
            judge_provider = _select_provider(config, judge_provider_name)
            state["provider"] = provider_name
            state["judge_provider"] = judge_provider_name
            state["status"] = "running"
            write_run(run_dir, state)
            execute_tree(config, run_dir, state, provider, judge_provider)
            print(f"Run: {state['id']} ({state['status']})")
            print(f"Report: {run_dir / 'report.md'}")
            print(_format_tree(state))
            return 0

        if args.command == "list":
            runs = list_runs(config)
            if not runs:
                print("No saved research runs.")
                return 0
            for state in runs:
                print(f"{state['id']}  {state['status']:<18} {state['calls_used']:>3} calls  {state['question']}")
            return 0

        if args.command == "tree":
            _, state = _get_run(config, args.run_id)
            print(_format_tree(state))
            return 0

        if args.command == "report":
            run_dir, state = _get_run(config, args.run_id)
            path = write_report(run_dir, state)
            print(path.read_text(encoding="utf-8"))
            return 0

        parser.error("Unknown command.")
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"research-tree: error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
