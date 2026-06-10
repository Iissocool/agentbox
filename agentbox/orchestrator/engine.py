"""Orchestrator engine - executes multi-agent pipelines with inter-agent communication."""

from __future__ import annotations

import json
import os
import re
import shlex
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..config import get_agent_config
from ..state import register_window
from ..tmux_mgr import TmuxManager
from .pipeline import Pipeline, PipelineStep, StepType

console = Console()

PIPELINE_STATE_DIR = Path.home() / ".agentbox" / "pipelines"


def _ensure_dir() -> None:
    PIPELINE_STATE_DIR.mkdir(parents=True, exist_ok=True)


def _save_pipeline_run(run_id: str, data: dict[str, Any]) -> None:
    _ensure_dir()
    path = PIPELINE_STATE_DIR / f"{run_id}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def _load_pipeline_run(run_id: str) -> dict[str, Any] | None:
    path = PIPELINE_STATE_DIR / f"{run_id}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


class Orchestrator:
    """Executes multi-agent pipelines, passing outputs between steps.

    The orchestrator:
    1. Creates a tmux session for the pipeline
    2. Runs each step sequentially (or in parallel)
    3. Captures output from each agent's tmux window
    4. Feeds previous outputs as context into subsequent step prompts
    5. Tracks pipeline state to disk for recovery/inspection
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.tmux_mgr = TmuxManager(config)

    def execute(
        self,
        pipeline: Pipeline,
        project_path: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a pipeline and return results."""
        if not project_path:
            project_path = os.getcwd()
        if not run_id:
            run_id = f"{pipeline.name}-{int(time.time())}"

        project_name = Path(project_path).name
        session_name = self.tmux_mgr.create_session(
            f"{project_name}-pipe", project_path
        )
        if not session_name:
            return {"status": "failed", "error": "Could not create tmux session"}

        context: dict[str, Any] = dict(pipeline.shared_context)
        step_results: dict[str, dict[str, Any]] = {}

        run_data = {
            "run_id": run_id,
            "pipeline_name": pipeline.name,
            "pipeline_desc": pipeline.description,
            "session_name": session_name,
            "project_path": project_path,
            "started_at": datetime.now().isoformat(),
            "status": "running",
            "steps": {},
            "context_keys": list(context.keys()),
        }
        _save_pipeline_run(run_id, run_data)

        console.print(Panel(
            f"[bold green]Pipeline: {pipeline.name}[/bold green]\n\n"
            f"{pipeline.description}\n\n"
            f"Steps: {len(pipeline.steps)}\n"
            f"Session: [cyan]{session_name}[/cyan]\n"
            f"Run ID: [dim]{run_id}[/dim]",
            title="Orchestrator",
            border_style="green",
        ))

        # Execute steps
        parallel_group: list[PipelineStep] = []
        for i, step in enumerate(pipeline.steps):
            if step.step_type == StepType.PARALLEL and i > 0:
                parallel_group.append(step)
                is_last = i == len(pipeline.steps) - 1
                next_seq = (not is_last and pipeline.steps[i + 1].step_type == StepType.SEQUENTIAL)
                if is_last or next_seq:
                    results = self._execute_parallel_group(
                        parallel_group, session_name, project_path, context
                    )
                    context.update(results)
                    step_results.update({k: {"status": "completed", "output": v} for k, v in results.items()})
                    parallel_group = []
            else:
                if parallel_group:
                    results = self._execute_parallel_group(
                        parallel_group, session_name, project_path, context
                    )
                    context.update(results)
                    step_results.update({k: {"status": "completed", "output": v} for k, v in results.items()})
                    parallel_group = []

                result = self._execute_step(step, session_name, project_path, context, i)
                if result["status"] == "completed":
                    context[step.step_id] = result["output"]
                    step_results[step.step_id] = result
                else:
                    step_results[step.step_id] = result
                    console.print(f"[red]Step '{step.step_id}' failed: {result.get('error', '')}[/red]")

            run_data["steps"] = step_results
            _save_pipeline_run(run_id, run_data)

        run_data["status"] = "completed"
        run_data["completed_at"] = datetime.now().isoformat()
        _save_pipeline_run(run_id, run_data)

        self._print_summary(run_id, step_results, session_name)
        return {
            "run_id": run_id,
            "status": "completed",
            "session_name": session_name,
            "steps": step_results,
        }

    def _execute_step(
        self, step: PipelineStep, session_name: str,
        project_path: str, context: dict[str, Any], step_index: int,
    ) -> dict[str, Any]:
        """Execute a single pipeline step."""
        resolved_prompt = self._resolve_step_prompt(step, context)

        console.print(Panel(
            f"[bold]Step {step_index + 1}: {step.role}[/bold] -> [cyan]{step.agent}[/cyan]\n\n"
            f"Prompt: [dim]{resolved_prompt[:200]}...[/dim]",
            title=f">> {step.step_id}",
            border_style="yellow",
        ))

        window_label = f"{step.role}-{step.agent}"
        agent_config = get_agent_config(self.config, step.agent)
        if not agent_config:
            return {"status": "failed", "error": f"Unknown agent: {step.agent}"}

        cmd = self._build_agent_command(step.agent, agent_config, resolved_prompt)
        window_name = self.tmux_mgr.add_agent_window(
            session_name, window_label, cmd, project_path
        )
        if not window_name:
            return {"status": "failed", "error": "Could not create tmux window"}

        register_window(
            session_name=session_name, window_name=window_name,
            agent_id=step.agent, role=step.role,
            project_path=project_path, project_name=Path(project_path).name,
            prompt=resolved_prompt[:200],
        )

        console.print(f"[dim]Waiting for {step.agent} ({step.role})...[/dim]")
        output = self._wait_for_output(session_name, window_name, step.timeout)

        if output:
            console.print(f"[green]Step '{step.step_id}' completed ({len(output)} chars)[/green]")
            return {"status": "completed", "output": output, "window": window_name}
        else:
            console.print(f"[yellow]Step '{step.step_id}' timed out[/yellow]")
            raw = self.tmux_mgr.capture_pane(session_name, window_name, lines=200)
            filtered = self._filter_output(raw, step.agent)
            return {
                "status": "completed" if filtered else "failed",
                "output": filtered or "(no output)",
                "window": window_name,
                "timed_out": not filtered,
            }

    def _execute_parallel_group(
        self, steps: list[PipelineStep], session_name: str,
        project_path: str, context: dict[str, Any],
    ) -> dict[str, str]:
        """Execute a group of steps in parallel."""
        console.print(f"[bold cyan]Running {len(steps)} steps in parallel[/bold cyan]")

        window_map: dict[str, str] = {}
        for step in steps:
            resolved_prompt = self._resolve_step_prompt(step, context)
            agent_config = get_agent_config(self.config, step.agent)
            if not agent_config:
                continue

            window_label = f"{step.role}-{step.agent}"
            cmd = self._build_agent_command(step.agent, agent_config, resolved_prompt)
            window_name = self.tmux_mgr.add_agent_window(
                session_name, window_label, cmd, project_path
            )
            if window_name:
                window_map[step.step_id] = window_name
                register_window(
                    session_name=session_name, window_name=window_name,
                    agent_id=step.agent, role=step.role,
                    project_path=project_path, project_name=Path(project_path).name,
                    prompt=resolved_prompt[:200],
                )

        max_timeout = max(s.timeout for s in steps)
        console.print(f"[dim]Waiting for parallel steps (max {max_timeout}s)...[/dim]")
        time.sleep(min(5, max_timeout))

        results: dict[str, str] = {}
        for step in steps:
            if step.step_id in window_map:
                window_name = window_map[step.step_id]
                output = self._wait_for_output(
                    session_name, window_name, min(step.timeout, max_timeout)
                )
                if not output:
                    raw = self.tmux_mgr.capture_pane(session_name, window_name, lines=200)
                    output = self._filter_output(raw, step.agent) or "(no output)"
                results[step.step_id] = output
                console.print(f"[green]Parallel step '{step.step_id}' done[/green]")
        return results

    def _resolve_step_prompt(self, step: PipelineStep, context: dict[str, Any]) -> str:
        """Resolve a step's prompt template with context."""
        if not step.prompt:
            return context.get("original_prompt", "")
        temp = Pipeline(name="temp")
        return temp.resolve_prompt(step, context)

    def _build_agent_command(self, agent_id: str, agent_config: dict[str, Any], prompt: str) -> str:
        """Build the shell command to run an agent with a prompt."""
        run_cmd = agent_config.get("run_cmd", agent_id)
        quoted = shlex.quote(prompt)
        if agent_id == "claude":
            return f"{run_cmd} -p {quoted}"
        if agent_id == "aider":
            return f"{run_cmd} --message {quoted}"
        return f"{run_cmd} {quoted}"

    def _wait_for_output(
        self, session_name: str, window_name: str,
        timeout: int = 300, poll_interval: int = 5,
    ) -> str | None:
        """Wait for an agent to produce output in a tmux window."""
        start = time.time()
        last_len = 0
        stable_count = 0

        while time.time() - start < timeout:
            time.sleep(poll_interval)
            raw = self.tmux_mgr.capture_pane(session_name, window_name, lines=200)
            filtered = self._filter_output(raw, "")
            if not filtered:
                continue
            cur_len = len(filtered)
            if cur_len > last_len:
                last_len = cur_len
                stable_count = 0
                continue
            stable_count += 1
            if stable_count >= 3 and cur_len > 50:
                return filtered
            if self._detect_prompt_return(raw):
                return filtered
        return None

    def _filter_output(self, raw_output: str, agent_id: str) -> str:
        """Filter tmux output to extract agent response."""
        if not raw_output:
            return ""
        ansi_re = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b\[.*?m')
        cleaned = ansi_re.sub('', raw_output)
        lines = cleaned.split('\n')

        start = 0
        for i, line in enumerate(lines):
            s = line.strip()
            if s and not s.startswith('$') and not s.startswith('>'):
                start = i
                break

        end = len(lines)
        while end > start and not lines[end - 1].strip():
            end -= 1

        result = '\n'.join(lines[start:end]).strip()
        for pat in [r'\$\s*$', r'>\s*$']:
            result = re.sub(pat, '', result).strip()
        return result

    def _detect_prompt_return(self, output: str) -> bool:
        """Detect if shell prompt has returned."""
        if not output:
            return False
        for line in output.strip().split('\n')[-3:]:
            s = line.strip()
            if s in ('$', '>', '#') or s.endswith('$') or s.endswith('>'):
                return True
        return False

    def _print_summary(self, run_id: str, step_results: dict[str, dict[str, Any]], session_name: str) -> None:
        """Print pipeline execution summary."""
        table = Table(title=f"Pipeline Results: {run_id}")
        table.add_column("Step", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Output", style="dim")
        table.add_column("Window", style="magenta")

        for step_id, result in step_results.items():
            status = result.get("status", "?")
            icon = "OK" if status == "completed" else "FAIL"
            out_len = f"{len(result.get('output', ''))} chars"
            window = result.get("window", "-")
            table.add_row(step_id, f"{icon} {status}", out_len, window)

        console.print(table)
        console.print(f"\n[dim]State saved: ~/.agentbox/pipelines/{run_id}.json[/dim]")
        console.print(f"[dim]Session: {session_name}[/dim]")

    @staticmethod
    def list_pipeline_runs() -> list[dict[str, Any]]:
        _ensure_dir()
        runs = []
        for path in sorted(PIPELINE_STATE_DIR.glob("*.json"), reverse=True):
            try:
                with open(path) as f:
                    data = json.load(f)
                runs.append({
                    "run_id": data.get("run_id", path.stem),
                    "pipeline": data.get("pipeline_name", "?"),
                    "status": data.get("status", "?"),
                    "started_at": data.get("started_at", "?"),
                    "steps_count": len(data.get("steps", {})),
                })
            except (json.JSONDecodeError, OSError):
                continue
        return runs

    @staticmethod
    def get_pipeline_run(run_id: str) -> dict[str, Any] | None:
        return _load_pipeline_run(run_id)

    @staticmethod
    def print_pipeline_runs() -> None:
        runs = Orchestrator.list_pipeline_runs()
        if not runs:
            console.print("[dim]No pipeline runs found.[/dim]")
            return

        table = Table(title="Pipeline Runs")
        table.add_column("Run ID", style="cyan")
        table.add_column("Pipeline", style="green")
        table.add_column("Status", style="bold")
        table.add_column("Steps", style="magenta")
        table.add_column("Started", style="dim")

        for run in runs:
            icon = "OK" if run["status"] == "completed" else "..."
            table.add_row(
                run["run_id"],
                run["pipeline"],
                f"{icon} {run['status']}",
                str(run["steps_count"]),
                run["started_at"][:19] if run["started_at"] != "?" else "?",
            )
        console.print(table)
