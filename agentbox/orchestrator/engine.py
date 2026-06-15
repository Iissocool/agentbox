"""Orchestrator engine -- executes multi-agent pipelines with inter-agent communication and persistent state tracking."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..config import get_agent_config
from ..sandbox import SandboxManager
from ..state import register_window
from ..tmux_mgr import TmuxManager
from ..event_bus import emit as _emit
from ..utils.commands import build_agent_command, build_docker_exec
from .pipeline import Pipeline, PipelineStep, StepType


# ── Module State ────────────────────────────────────────

console = Console()

PIPELINE_STATE_DIR = Path.home() / ".agentbox" / "pipelines"


# ── Persistence Helpers ─────────────────────────────────


def _ensure_dir() -> None:
    """Create the pipeline state directory if it does not already exist."""
    PIPELINE_STATE_DIR.mkdir(parents=True, exist_ok=True)


def _save_pipeline_run(run_id: str, data: dict[str, Any]) -> None:
    """Persist a pipeline run's data to disk as JSON.

    Args:
        run_id: Unique identifier for the run (used as the filename stem).
        data: Serialisable dictionary of run metadata and step results.
    """
    _ensure_dir()
    path = PIPELINE_STATE_DIR / f"{run_id}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def _load_pipeline_run(run_id: str) -> dict[str, Any] | None:
    """Load a previously saved pipeline run from disk.

    Args:
        run_id: Unique identifier for the run to load.

    Returns:
        The run data dictionary, or ``None`` if the file does not exist.
    """
    path = PIPELINE_STATE_DIR / f"{run_id}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


# ── Orchestrator ────────────────────────────────────────


class Orchestrator:
    """Execute multi-agent pipelines, passing outputs between steps.

    The orchestrator:

    1. Creates a tmux session for the pipeline.
    2. Runs each step sequentially (or in parallel).
    3. Captures output from each agent's tmux window.
    4. Feeds previous outputs as context into subsequent step prompts.
    5. Tracks pipeline state to disk for recovery and inspection.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialise the orchestrator with the given project configuration.

        Args:
            config: Top-level agentbox configuration dictionary.
        """
        self.config = config
        self.tmux_mgr = TmuxManager(config)
        self.sandbox_mgr = SandboxManager(config)

    # ── Public API ──────────────────────────────────────

    def execute(
        self,
        pipeline: Pipeline,
        project_path: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a pipeline end-to-end and return the aggregated results.

        Args:
            pipeline: The :class:`Pipeline` to run.
            project_path: Root directory for the project. Defaults to ``os.getcwd()``.
            run_id: Unique run identifier. Auto-generated from the pipeline name
                and current timestamp if not provided.

        Returns:
            A dictionary containing ``run_id``, ``status``, ``session_name``,
            and a ``steps`` mapping of step IDs to their result dictionaries.
        """
        if not project_path:
            project_path = os.getcwd()
        if not run_id:
            run_id = f"{pipeline.name}-{int(time.time())}"

        project_name = Path(project_path).name
        session_name = self.tmux_mgr.create_session(
            f"{project_name}-pipe", project_path,
        )
        if not session_name:
            return {"status": "failed", "error": "Could not create tmux session"}

        context: dict[str, Any] = dict(pipeline.shared_context)
        step_results: dict[str, dict[str, Any]] = {}

        run_data: dict[str, Any] = {
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
        _emit("pipeline_event", "orchestrator", {"pipeline": pipeline.name, "event": "started", "run_id": run_id})

        console.print(
            Panel(
                f"[bold green]Pipeline: {pipeline.name}[/bold green]\n\n"
                f"{pipeline.description}\n\n"
                f"Steps: {len(pipeline.steps)}\n"
                f"Session: [cyan]{session_name}[/cyan]\n"
                f"Run ID: [dim]{run_id}[/dim]",
                title="Orchestrator",
                border_style="green",
            )
        )

        # ── Step Execution ──────────────────────────────
        parallel_group: list[PipelineStep] = []
        for i, step in enumerate(pipeline.steps):
            is_last = i == len(pipeline.steps) - 1
            next_is_seq = (
                not is_last
                and pipeline.steps[i + 1].step_type == StepType.SEQUENTIAL
            )

            if step.step_type == StepType.PARALLEL:
                parallel_group.append(step)

                # Flush the group when the pipeline ends or a sequential step follows.
                if is_last or next_is_seq:
                    results = self._execute_parallel_group(
                        parallel_group, session_name, project_path, context,
                    )
                    context.update(results)
                    step_results.update(
                        {k: {"status": "completed", "output": v} for k, v in results.items()}
                    )
                    parallel_group = []
            else:
                # Flush any pending parallel group before a sequential step.
                if parallel_group:
                    results = self._execute_parallel_group(
                        parallel_group, session_name, project_path, context,
                    )
                    context.update(results)
                    step_results.update(
                        {k: {"status": "completed", "output": v} for k, v in results.items()}
                    )
                    parallel_group = []

                result = self._execute_step(
                    step, session_name, project_path, context, i,
                )
                if result["status"] == "completed":
                    context[step.step_id] = result["output"]
                    step_results[step.step_id] = result
                else:
                    step_results[step.step_id] = result
                    console.print(
                        f"[red]Step '{step.step_id}' failed: "
                        f"{result.get('error', '')}[/red]"
                    )

            run_data["steps"] = step_results
            _save_pipeline_run(run_id, run_data)

        run_data["status"] = "completed"
        _emit("pipeline_event", "orchestrator", {"pipeline": pipeline.name, "event": "completed", "run_id": run_id})
        run_data["completed_at"] = datetime.now().isoformat()
        _save_pipeline_run(run_id, run_data)

        self._print_summary(run_id, step_results, session_name)

        return {
            "run_id": run_id,
            "status": "completed",
            "session_name": session_name,
            "steps": step_results,
        }

    # ── Step Execution Internals ────────────────────────

    @staticmethod
    def _skill_pre_hook(step, agent_config: dict) -> dict | None:
        """Resolve skills for a pipeline step and return skill context."""
        from ..agents.contracts import load_contract
        from ..skills import load_skill
        contract = load_contract(step.agent)
        if not contract:
            return None
        skills = contract.get("skills", [])
        policy = contract.get("policy", {})
        skill_details = []
        for skill_name in skills:
            skill = load_skill(skill_name)
            if skill:
                skill_details.append(skill)
        return {
            "contract": contract,
            "skills": skill_details,
            "policy": policy,
            "max_steps": policy.get("max_steps", 10),
            "require_diff": policy.get("require_diff", False),
        }

    def _execute_step(
        self,
        step: PipelineStep,
        session_name: str,
        project_path: str,
        context: dict[str, Any],
        step_index: int,
    ) -> dict[str, Any]:
        """Execute a single pipeline step inside a Docker sandbox.

        Args:
            step: The pipeline step to execute.
            session_name: Tmux session housing the pipeline.
            project_path: Root directory of the project.
            context: Shared context for prompt resolution.
            step_index: Zero-based position of this step in the pipeline.

        Returns:
            A result dictionary with at least ``status`` and ``output`` keys.
        """
        resolved_prompt = self._resolve_step_prompt(step, context)

        console.print(
            Panel(
                f"[bold]Step {step_index + 1}: {step.role}[/bold] -> [cyan]{step.agent}[/cyan]\n\n"
                f"Prompt: [dim]{resolved_prompt[:200]}...[/dim]",
                title=f">> {step.step_id}",
                border_style="yellow",
            )
        )

        window_label = f"{step.role}-{step.agent}"
        agent_config = get_agent_config(self.config, step.agent)
        if not agent_config:
            return {"status": "failed", "error": f"Unknown agent: {step.agent}"}

        # Create sandbox for this agent.
        project_name = Path(project_path).name
        sandbox_name = f"{step.agent}-{project_name}"
        sandbox = self.sandbox_mgr.create_sandbox(
            name=sandbox_name,
            agent_id=step.agent,
            project_path=project_path,
        )
        if not sandbox:
            return {
                "status": "failed",
                "error": f"Could not create sandbox for {step.agent}",
            }

        cmd = build_agent_command(
            step.agent, agent_config.get("run_cmd", step.agent), resolved_prompt,
        )
        docker_cmd = build_docker_exec(f"agentbox-{sandbox_name}", cmd)
        window_name = self.tmux_mgr.add_agent_window(
            session_name, window_label, docker_cmd, project_path,
        )
        if not window_name:
            return {"status": "failed", "error": "Could not create tmux window"}

        register_window(
            session_name=session_name,
            window_name=window_name,
            agent_id=step.agent,
            role=step.role,
            project_path=project_path,
            project_name=project_name,
            prompt=resolved_prompt[:200],
            sandbox=True,
        )

        console.print(f"[dim]Waiting for {step.agent} ({step.role})...[/dim]")
        output = self._wait_for_output(session_name, window_name, step.timeout)

        if output:
            console.print(
                f"[green]Step '{step.step_id}' completed ({len(output)} chars)[/green]"
            )
            return {"status": "completed", "output": output, "window": window_name}

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
        self,
        steps: list[PipelineStep],
        session_name: str,
        project_path: str,
        context: dict[str, Any],
    ) -> dict[str, str]:
        """Execute a group of steps in parallel, each in its own Docker sandbox.

        Args:
            steps: Pipeline steps to run concurrently.
            session_name: Tmux session housing the pipeline.
            project_path: Root directory of the project.
            context: Shared context for prompt resolution.

        Returns:
            Mapping of step IDs to their captured output strings.
        """
        console.print(
            f"[bold cyan]Running {len(steps)} steps in parallel[/bold cyan]"
        )

        project_name = Path(project_path).name
        window_map: dict[str, str] = {}

        for step in steps:
            resolved_prompt = self._resolve_step_prompt(step, context)
            agent_config = get_agent_config(self.config, step.agent)
            if not agent_config:
                continue

            sandbox_name = f"{step.agent}-{project_name}"
            sandbox = self.sandbox_mgr.create_sandbox(
                name=sandbox_name,
                agent_id=step.agent,
                project_path=project_path,
            )
            if not sandbox:
                console.print(
                    f"[yellow]Warning: Could not create sandbox for "
                    f"{step.agent}, skipping[/yellow]"
                )
                continue

            window_label = f"{step.role}-{step.agent}"
            cmd = build_agent_command(
                step.agent, agent_config.get("run_cmd", step.agent), resolved_prompt,
            )
            docker_cmd = build_docker_exec(f"agentbox-{sandbox_name}", cmd)
            window_name = self.tmux_mgr.add_agent_window(
                session_name, window_label, docker_cmd, project_path,
            )

            if window_name:
                window_map[step.step_id] = window_name
                register_window(
                    session_name=session_name,
                    window_name=window_name,
                    agent_id=step.agent,
                    role=step.role,
                    project_path=project_path,
                    project_name=project_name,
                    prompt=resolved_prompt[:200],
                    sandbox=True,
                )

        max_timeout = max(s.timeout for s in steps)
        console.print(
            f"[dim]Waiting for parallel steps (max {max_timeout}s)...[/dim]"
        )
        time.sleep(min(5, max_timeout))

        results: dict[str, str] = {}
        for step in steps:
            if step.step_id in window_map:
                window_name = window_map[step.step_id]
                output = self._wait_for_output(
                    session_name, window_name, min(step.timeout, max_timeout),
                )
                if not output:
                    raw = self.tmux_mgr.capture_pane(
                        session_name, window_name, lines=200,
                    )
                    output = self._filter_output(raw, step.agent) or "(no output)"
                results[step.step_id] = output
                console.print(
                    f"[green]Parallel step '{step.step_id}' done[/green]"
                )

        return results

    # ── Prompt Resolution ───────────────────────────────

    def _resolve_step_prompt(
        self, step: PipelineStep, context: dict[str, Any],
    ) -> str:
        """Resolve a step's prompt template against the shared context.

        Falls back to ``context["original_prompt"]`` when the step has no prompt.

        Args:
            step: The pipeline step whose prompt will be resolved.
            context: Key-value mapping used for placeholder substitution.

        Returns:
            The fully resolved prompt string.
        """
        if not step.prompt:
            return context.get("original_prompt", "")

        temp = Pipeline(name="temp")
        return temp.resolve_prompt(step, context)

    # ── Output Capture ──────────────────────────────────

    def _wait_for_output(
        self,
        session_name: str,
        window_name: str,
        timeout: int = 300,
        poll_interval: int = 5,
    ) -> str | None:
        """Poll a tmux window until the agent produces stable output.

        Stability is declared when the output length has not changed for
        three consecutive polls and exceeds 50 characters, or when a shell
        prompt is detected in the pane.

        Args:
            session_name: Tmux session containing the target window.
            window_name: Tmux window to monitor.
            timeout: Maximum seconds to wait before giving up.
            poll_interval: Seconds between each poll.

        Returns:
            The filtered output string, or ``None`` if the timeout expires.
        """
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
        """Strip ANSI escape codes and shell artefacts from raw tmux output.

        Args:
            raw_output: Unprocessed tmux pane capture.
            agent_id: Agent identifier (reserved for future agent-specific filtering).

        Returns:
            Cleaned output string with leading/trailing noise removed.
        """
        if not raw_output:
            return ""

        ansi_re = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b\[.*?m")
        cleaned = ansi_re.sub("", raw_output)
        lines = cleaned.split("\n")

        # Skip leading shell prompts and empty lines.
        start = 0
        for i, line in enumerate(lines):
            s = line.strip()
            if s and not s.startswith("$") and not s.startswith(">"):
                start = i
                break

        # Trim trailing blank lines.
        end = len(lines)
        while end > start and not lines[end - 1].strip():
            end -= 1

        result = "\n".join(lines[start:end]).strip()
        for pat in [r"\$\s*$", r">\s*$"]:
            result = re.sub(pat, "", result).strip()

        return result

    def _detect_prompt_return(self, output: str) -> bool:
        """Detect whether a shell prompt has returned in the tmux output.

        Args:
            output: Raw tmux pane content to inspect.

        Returns:
            ``True`` if a shell prompt indicator is found in the last three lines.
        """
        if not output:
            return False

        for line in output.strip().split("\n")[-3:]:
            s = line.strip()
            if s in ("$", ">", "#") or s.endswith("$") or s.endswith(">"):
                return True

        return False

    # ── Reporting ───────────────────────────────────────

    def _print_summary(
        self,
        run_id: str,
        step_results: dict[str, dict[str, Any]],
        session_name: str,
    ) -> None:
        """Print a rich-formatted table summarising pipeline step results.

        Args:
            run_id: Unique identifier for the pipeline run.
            step_results: Mapping of step IDs to their result dictionaries.
            session_name: Tmux session that hosted the pipeline.
        """
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

    # ── Class-Level Queries ─────────────────────────────

    @staticmethod
    def list_pipeline_runs() -> list[dict[str, Any]]:
        """List all saved pipeline runs, most recent first.

        Returns:
            A list of summary dictionaries, each containing ``run_id``,
            ``pipeline``, ``status``, ``started_at``, and ``steps_count``.
        """
        _ensure_dir()
        runs: list[dict[str, Any]] = []

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
        """Retrieve a single pipeline run by its identifier.

        Args:
            run_id: Unique identifier for the run to fetch.

        Returns:
            The full run data dictionary, or ``None`` if not found.
        """
        return _load_pipeline_run(run_id)

    @staticmethod
    def print_pipeline_runs() -> None:
        """Display a rich-formatted table of all pipeline runs."""
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
