from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import uuid
from typing import Any

from .config import ProjectConfig


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def create_run(
    config: ProjectConfig, question: str, provider: str, judge_provider: str
) -> tuple[Path, dict[str, Any]]:
    run_id = new_run_id()
    run_dir = config.data_dir / run_id
    (run_dir / "branches").mkdir(parents=True, exist_ok=False)
    state: dict[str, Any] = {
        "schema_version": 1,
        "id": run_id,
        "project": config.name,
        "question": question,
        "provider": provider,
        "judge_provider": judge_provider,
        "status": "running",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "calls_used": 0,
        "root_ids": [],
        "nodes": {},
        "findings": [],
        "settings": {},
        "error": "",
    }
    angles = config.tree.initial_angles or (
        "Map the opportunity space and identify primary demand evidence.",
        "Find user pain, workarounds, and complaints about current options.",
        "Search specialist segments and test overlooked assumptions.",
    )
    from .models import BranchNode, new_id

    for index in range(config.tree.initial_branches):
        angle = angles[index] if index < len(angles) else f"Independent research angle {index + 1}."
        node = BranchNode(id=new_id(), question=question, angle=angle, depth=0)
        state["root_ids"].append(node.id)
        state["nodes"][node.id] = node.to_dict()
    write_run(run_dir, state)
    return run_dir, state


def write_run(run_dir: Path, state: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _utc_now()
    destination = run_dir / "run.json"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=run_dir, prefix=".run-", suffix=".tmp", delete=False
    ) as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_name = handle.name
    Path(temp_name).replace(destination)


def read_run(run_dir: Path) -> dict[str, Any]:
    with (run_dir / "run.json").open("r", encoding="utf-8") as handle:
        state = json.load(handle)
    if state.get("schema_version") != 1:
        raise ValueError(f"Unsupported run format in {run_dir}.")
    return state


def locate_run(config: ProjectConfig, run_id: str) -> Path:
    candidate = (config.data_dir / run_id).resolve()
    if not candidate.is_relative_to(config.data_dir.resolve()):
        raise ValueError("Run IDs must name a run inside the configured data directory.")
    if not (candidate / "run.json").is_file():
        raise FileNotFoundError(f"No saved run named {run_id!r}.")
    return candidate


def latest_run_dir(config: ProjectConfig) -> Path:
    runs = [path for path in config.data_dir.iterdir() if path.is_dir() and (path / "run.json").is_file()]
    if not runs:
        raise FileNotFoundError("There are no saved research runs yet.")
    return max(runs, key=lambda path: path.stat().st_mtime)


def list_runs(config: ProjectConfig) -> list[dict[str, Any]]:
    if not config.data_dir.exists():
        return []
    result: list[dict[str, Any]] = []
    for path in config.data_dir.iterdir():
        if not path.is_dir() or not (path / "run.json").is_file():
            continue
        try:
            state = read_run(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        result.append(state)
    return sorted(result, key=lambda item: item.get("created_at", ""), reverse=True)
