from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any


DEFAULT_CONFIG = '''# Research Tree project settings. Provider commands are trusted local commands.
[project]
name = "My Research"
data_dir = ".research-tree/runs"

[tree]
initial_branches = 3
children_per_branch = 2
max_depth = 2
max_attempts_per_branch = 3
max_nodes = 25
max_calls = 60
parallelism = 3
strictness = 0.55
random_context_ratio = 0.18
# Set to an integer to reproduce the same random association seeds.
seed = ""

initial_angles = [
  "Map the broad opportunity space and locate demand signals.",
  "Look for user complaints, workarounds, and weak current solutions.",
  "Search specialist and overlooked segments; test whether evidence supports demand.",
]

[providers]
default = "codex"
judge = "codex"

[providers.codex]
command = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only", "--output-last-message", "{output}", "-"]
prompt_transport = "stdin"
output_file = "{output}"
timeout_seconds = 900

# Claude Code example. Install Claude Code and choose a prompt transport supported by
# your installed CLI; this example passes the prompt as one argument.
[providers.claude]
command = ["claude", "-p", "{prompt}"]
prompt_transport = "argument"
timeout_seconds = 900
'''


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    command: tuple[str, ...]
    prompt_transport: str = "stdin"
    output_file: str | None = None
    timeout_seconds: int = 900


@dataclass(frozen=True)
class TreeConfig:
    initial_branches: int = 3
    children_per_branch: int = 2
    max_depth: int = 2
    max_attempts_per_branch: int = 3
    max_nodes: int = 25
    max_calls: int = 60
    parallelism: int = 3
    strictness: float = 0.55
    random_context_ratio: float = 0.18
    seed: str = ""
    initial_angles: tuple[str, ...] = ()

    @property
    def score_threshold(self) -> int:
        return round(30 + self.strictness * 60)


@dataclass(frozen=True)
class ProjectConfig:
    root: Path
    name: str
    data_dir: Path
    default_provider: str
    default_judge_provider: str
    tree: TreeConfig
    providers: dict[str, ProviderConfig]


def _positive_int(section: dict[str, Any], key: str, default: int, minimum: int = 1) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"Configuration '{key}' must be an integer >= {minimum}.")
    return value


def load_config(root: Path) -> ProjectConfig:
    root = root.resolve()
    config_path = root / "research-tree.toml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"No {config_path.name} in {root}. Run 'research-tree init' first."
        )
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    project = raw.get("project", {})
    tree_raw = raw.get("tree", {})
    providers_raw = raw.get("providers", {})
    ratio = float(tree_raw.get("random_context_ratio", 0.18))
    strictness = float(tree_raw.get("strictness", 0.55))
    if not 0 <= ratio <= 0.5:
        raise ValueError("tree.random_context_ratio must be between 0 and 0.5.")
    if not 0 <= strictness <= 1:
        raise ValueError("tree.strictness must be between 0 and 1.")

    angles = tree_raw.get("initial_angles", [])
    if not isinstance(angles, list) or any(not isinstance(item, str) for item in angles):
        raise ValueError("tree.initial_angles must be an array of strings.")
    tree = TreeConfig(
        initial_branches=_positive_int(tree_raw, "initial_branches", 3),
        children_per_branch=_positive_int(tree_raw, "children_per_branch", 2, minimum=2),
        max_depth=_positive_int(tree_raw, "max_depth", 2, minimum=0),
        max_attempts_per_branch=_positive_int(tree_raw, "max_attempts_per_branch", 3),
        max_nodes=_positive_int(tree_raw, "max_nodes", 25),
        max_calls=_positive_int(tree_raw, "max_calls", 60),
        parallelism=_positive_int(tree_raw, "parallelism", 3),
        strictness=strictness,
        random_context_ratio=ratio,
        seed=str(tree_raw.get("seed", "")),
        initial_angles=tuple(angles),
    )

    provider_configs: dict[str, ProviderConfig] = {}
    for name, value in providers_raw.items():
        if name in {"default", "judge"}:
            continue
        if not isinstance(value, dict):
            raise ValueError(f"providers.{name} must be a table.")
        command = value.get("command")
        if not isinstance(command, list) or not command or any(not isinstance(arg, str) for arg in command):
            raise ValueError(f"providers.{name}.command must be a non-empty array of strings.")
        transport = str(value.get("prompt_transport", "stdin"))
        if transport not in {"stdin", "argument"}:
            raise ValueError(f"providers.{name}.prompt_transport must be 'stdin' or 'argument'.")
        output_file = value.get("output_file")
        if output_file is not None and not isinstance(output_file, str):
            raise ValueError(f"providers.{name}.output_file must be a string.")
        provider_configs[name] = ProviderConfig(
            name=name,
            command=tuple(command),
            prompt_transport=transport,
            output_file=output_file,
            timeout_seconds=_positive_int(value, "timeout_seconds", 900),
        )

    default_provider = str(providers_raw.get("default", "codex"))
    judge_provider = str(providers_raw.get("judge", default_provider))
    if default_provider not in provider_configs:
        raise ValueError(f"Default provider '{default_provider}' is not configured.")
    if judge_provider not in provider_configs:
        raise ValueError(f"Judge provider '{judge_provider}' is not configured.")
    if tree.max_nodes < tree.initial_branches:
        raise ValueError("tree.max_nodes must be at least tree.initial_branches.")
    data_dir = (root / str(project.get("data_dir", ".research-tree/runs"))).resolve()
    if not data_dir.is_relative_to(root):
        raise ValueError("project.data_dir must stay inside the project folder.")
    return ProjectConfig(
        root=root,
        name=str(project.get("name", root.name)),
        data_dir=data_dir,
        default_provider=default_provider,
        default_judge_provider=judge_provider,
        tree=tree,
        providers=provider_configs,
    )

