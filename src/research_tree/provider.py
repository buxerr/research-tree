from __future__ import annotations

from pathlib import Path
import subprocess
import uuid

from .config import ProviderConfig


class ProviderError(RuntimeError):
    pass


class CommandProvider:
    """Run a configured local agent CLI without invoking a shell."""

    def __init__(self, config: ProviderConfig):
        self.config = config

    def complete(self, prompt: str, run_dir: Path) -> str:
        temp_dir = run_dir / ".tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        output_path = temp_dir / f"provider-{uuid.uuid4().hex}.txt"
        args: list[str] = []
        prompt_inserted = False
        for item in self.config.command:
            if "{prompt}" in item:
                args.append(item.replace("{prompt}", prompt))
                prompt_inserted = True
            else:
                args.append(item.replace("{output}", str(output_path)).replace("{cwd}", str(run_dir)))
        stdin_text: str | None = None
        if self.config.prompt_transport == "stdin" and not prompt_inserted:
            stdin_text = prompt
        elif not prompt_inserted:
            args.append(prompt)

        try:
            try:
                result = subprocess.run(
                    args,
                    cwd=run_dir,
                    input=stdin_text,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=self.config.timeout_seconds,
                    check=False,
                    shell=False,
                )
            except FileNotFoundError as exc:
                raise ProviderError(f"Could not start provider command '{args[0]}': {exc}") from exc
            except subprocess.TimeoutExpired as exc:
                raise ProviderError(f"Provider timed out after {self.config.timeout_seconds} seconds.") from exc

            output_setting = self.config.output_file
            if output_setting:
                path_value = output_setting.replace("{output}", str(output_path)).replace("{cwd}", str(run_dir))
                candidate = Path(path_value)
                if not candidate.is_absolute():
                    candidate = run_dir / candidate
                if candidate.exists():
                    output = candidate.read_text(encoding="utf-8", errors="replace")
                else:
                    output = result.stdout
            else:
                output = result.stdout

            if result.returncode != 0:
                diagnostic = result.stderr.strip()[-1600:]
                raise ProviderError(
                    f"Provider exited with code {result.returncode}."
                    + (f" Details: {diagnostic}" if diagnostic else "")
                )
            if not output.strip():
                raise ProviderError("Provider returned no final text.")
            return output.strip()
        finally:
            output_path.unlink(missing_ok=True)

