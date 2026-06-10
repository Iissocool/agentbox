"""Workflow engine for project-aware agent tasks."""

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from ..config import get_agent_config
from ..sandbox import SandboxManager
from ..state import register_window
from ..tmux_mgr import TmuxManager

console = Console()


class WorkflowEngine:
    """Coordinates AGENTS.md context, git review actions, tests, and agent launch."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.sandbox_mgr = SandboxManager(config)
        self.tmux_mgr = TmuxManager(config)

    def load_agents_md(self, project_path: str | Path) -> str:
        """Load project AGENTS.md guidance if it exists."""
        agents_file = Path(project_path).expanduser().resolve() / "AGENTS.md"
        if not agents_file.exists():
            return ""
        try:
            return agents_file.read_text(encoding="utf-8")
        except OSError as exc:
            console.print(f"[yellow]Could not read AGENTS.md: {exc}[/yellow]")
            return ""

    def inject_agents_md(self, prompt: str, project_path: str | Path) -> str:
        """Append AGENTS.md instructions to a prompt."""
        agents_md = self.load_agents_md(project_path)
        if not agents_md.strip():
            return prompt

        return (
            f"{prompt}\n\n"
            "Project agent instructions from AGENTS.md:\n"
            "---\n"
            f"{agents_md.strip()}\n"
            "---"
        )

    def is_git_repo(self, project_path: str | Path) -> bool:
        """Return True when project_path is inside a git repository."""
        result = self._run_git(["rev-parse", "--is-inside-work-tree"], project_path)
        return result.returncode == 0 and result.stdout.strip() == "true"

    def get_git_diff(self, project_path: str | Path) -> str:
        """Return the full git diff, including staged and unstaged changes."""
        unstaged = self._run_git(["diff", "--"], project_path)
        staged = self._run_git(["diff", "--cached", "--"], project_path)
        parts = []
        if staged.stdout.strip():
            parts.append("# Staged changes\n" + staged.stdout)
        if unstaged.stdout.strip():
            parts.append("# Unstaged changes\n" + unstaged.stdout)
        return "\n".join(parts)

    def get_git_diff_stats(self, project_path: str | Path) -> dict[str, Any]:
        """Return git diff stats and changed file status."""
        stat = self._run_git(["diff", "--stat", "HEAD", "--"], project_path)
        names = self._run_git(["status", "--short"], project_path)
        files = [line.rstrip() for line in names.stdout.splitlines() if line.strip()]
        return {
            "stat": stat.stdout.strip(),
            "files": files,
            "has_changes": bool(files),
        }

    def print_diff_summary(self, project_path: str | Path) -> bool:
        """Print a formatted summary of current git changes."""
        if not self.is_git_repo(project_path):
            console.print(f"[red]Not a git repository:[/red] {project_path}")
            return False

        stats = self.get_git_diff_stats(project_path)
        if not stats["has_changes"]:
            console.print("[green]Working tree clean.[/green]")
            return True

        table = Table(title="Git Changes")
        table.add_column("Status", style="yellow", width=8)
        table.add_column("File", style="cyan")
        for item in stats["files"]:
            status = item[:2].strip() or "?"
            path = item[3:] if len(item) > 3 else item
            table.add_row(status, path)
        console.print(table)

        if stats["stat"]:
            console.print(Panel(stats["stat"], title="Diff Stat", border_style="blue"))
        return True

    def merge_changes(self, project_path: str | Path, message: str) -> bool:
        """Stage all changes and commit them."""
        if not self.is_git_repo(project_path):
            console.print(f"[red]Not a git repository:[/red] {project_path}")
            return False

        if not self.get_git_diff_stats(project_path)["has_changes"]:
            console.print("[yellow]No changes to commit.[/yellow]")
            return False

        add = self._run_git(["add", "-A"], project_path)
        if add.returncode != 0:
            console.print(f"[red]git add failed:[/red] {add.stderr.strip()}")
            return False

        commit = self._run_git(["commit", "-m", message], project_path)
        if commit.returncode != 0:
            console.print(f"[red]git commit failed:[/red] {commit.stderr.strip()}")
            return False

        console.print(Panel(commit.stdout.strip(), title="Committed", border_style="green"))
        return True

    def discard_changes(self, project_path: str | Path) -> bool:
        """Discard tracked and untracked changes in the project."""
        if not self.is_git_repo(project_path):
            console.print(f"[red]Not a git repository:[/red] {project_path}")
            return False

        reset = self._run_git(["reset", "--", "."], project_path)
        checkout = self._run_git(["checkout", "--", "."], project_path)
        clean = self._run_git(["clean", "-fd"], project_path)
        if reset.returncode != 0 or checkout.returncode != 0 or clean.returncode != 0:
            console.print("[red]Failed to discard all changes.[/red]")
            if reset.stderr:
                console.print(reset.stderr.strip())
            if checkout.stderr:
                console.print(checkout.stderr.strip())
            if clean.stderr:
                console.print(clean.stderr.strip())
            return False

        console.print("[green]Discarded working tree changes.[/green]")
        return True

    def detect_test_command(self, project_path: str | Path) -> str | None:
        """Detect a likely project test command."""
        path = Path(project_path).expanduser().resolve()
        checks = [
            (path / "pyproject.toml", "pytest"),
            (path / "pytest.ini", "pytest"),
            (path / "setup.cfg", "pytest"),
            (path / "package.json", "npm test"),
            (path / "go.mod", "go test ./..."),
            (path / "Cargo.toml", "cargo test"),
        ]
        for marker, command in checks:
            if marker.exists():
                return command
        if (path / "requirements.txt").exists():
            return "pytest"
        return None

    def run_tests(
        self,
        project_path: str | Path,
        command: str | None = None,
        timeout: int = 600,
    ) -> dict[str, Any]:
        """Run the detected or provided test command."""
        test_cmd = command or self.detect_test_command(project_path)
        if not test_cmd:
            return {
                "command": "",
                "returncode": 1,
                "stdout": "",
                "stderr": "No test command detected. Pass --command.",
            }

        try:
            result = subprocess.run(
                test_cmd,
                cwd=str(Path(project_path).expanduser().resolve()),
                capture_output=True,
                text=True,
                shell=True,
                timeout=timeout,
            )
            return {
                "command": test_cmd,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except FileNotFoundError as exc:
            return {
                "command": test_cmd,
                "returncode": 127,
                "stdout": "",
                "stderr": str(exc),
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "command": test_cmd,
                "returncode": 124,
                "stdout": exc.stdout or "",
                "stderr": f"Test command timed out after {timeout} seconds.",
            }

    def print_test_results(self, results: dict[str, Any]) -> bool:
        """Print formatted test output and return whether tests passed."""
        command = results.get("command") or "(none)"
        returncode = int(results.get("returncode", 1))
        passed = returncode == 0
        color = "green" if passed else "red"
        status = "passed" if passed else f"failed ({returncode})"

        console.print(Panel(
            f"Command: [cyan]{command}[/cyan]\nStatus: [{color}]{status}[/{color}]",
            title="Test Results",
            border_style=color,
        ))

        output = "\n".join(
            part for part in [results.get("stdout", ""), results.get("stderr", "")]
            if part.strip()
        ).strip()
        if output:
            console.print(Syntax(output, "text", word_wrap=True))
        return passed

    def ask(
        self,
        prompt: str,
        agent_id: str = "claude",
        project_path: str | Path | None = None,
        use_sandbox: bool = True,
        role: str | None = None,
        attach: bool = True,
    ) -> bool:
        """Launch an agent with project instructions injected into the prompt."""
        path = Path(project_path or os.getcwd()).expanduser().resolve()
        agent_config = get_agent_config(self.config, agent_id)
        if not agent_config:
            console.print(f"[red]Unknown agent: {agent_id}[/red]")
            return False

        injected_prompt = self.inject_agents_md(prompt, path)
        session_name = self.tmux_mgr.create_session(path.name, str(path))
        if not session_name:
            return False

        window_label = f"{role}-{agent_id}" if role else agent_id
        if use_sandbox:
            started = self._launch_sandbox_agent(
                agent_id, agent_config, session_name, path, injected_prompt, window_label, role
            )
        else:
            started = self._launch_local_agent(
                agent_id, agent_config, session_name, path, injected_prompt, window_label, role
            )

        if started and attach:
            console.print("[dim]Attaching to tmux session... (Ctrl+B then D to detach)[/dim]")
            self.tmux_mgr.attach_session(session_name)
        return started

    def review(
        self,
        project_path: str | Path,
        auto_test: bool = True,
        test_cmd: str | None = None,
    ) -> bool:
        """Review current changes, optionally run tests, then merge or discard interactively."""
        if not self.print_diff_summary(project_path):
            return False

        stats = self.get_git_diff_stats(project_path)
        if not stats["has_changes"]:
            return True

        tests_passed = True
        if auto_test:
            results = self.run_tests(project_path, test_cmd)
            tests_passed = self.print_test_results(results)

        default_action = "merge" if tests_passed else "skip"
        action = click.prompt(
            "Action",
            type=click.Choice(["merge", "discard", "skip"], case_sensitive=False),
            default=default_action,
            show_choices=True,
        ).lower()

        if action == "merge":
            message = click.prompt("Commit message", default="Update project")
            return self.merge_changes(project_path, message)
        if action == "discard":
            if click.confirm("Discard all working tree changes?", default=False):
                return self.discard_changes(project_path)
            return False

        console.print("[yellow]Skipped merge/discard.[/yellow]")
        return tests_passed

    def _launch_local_agent(
        self,
        agent_id: str,
        agent_config: dict[str, Any],
        session_name: str,
        project_path: Path,
        prompt: str,
        window_label: str,
        role: str | None,
    ) -> bool:
        cli_name = agent_config.get("cli", agent_id)
        if not shutil.which(cli_name):
            console.print(f"[yellow]'{cli_name}' not found locally.[/yellow]")
            console.print(f"[dim]Install with: {agent_config.get('install_cmd', 'N/A')}[/dim]")
            console.print("[dim]Without --local, it will run in Docker sandbox automatically.[/dim]")
            return False

        cmd = self._agent_command(agent_id, agent_config, prompt)
        window_name = self.tmux_mgr.add_agent_window(session_name, window_label, cmd, str(project_path))
        if not window_name:
            return False

        register_window(
            session_name=session_name,
            window_name=window_name,
            agent_id=agent_id,
            role=role,
            project_path=str(project_path),
            project_name=project_path.name,
            sandbox=False,
            prompt=prompt,
        )
        console.print(Panel(
            f"[green]Agent started[/green]\n\n"
            f"Agent: [cyan]{agent_id}[/cyan]\n"
            f"Session: [cyan]{session_name}[/cyan]\n"
            f"Window: [cyan]{window_name}[/cyan]\n"
            f"Mode: [magenta]local[/magenta]",
            title="Ask Workflow",
            border_style="green",
        ))
        return True

    def _launch_sandbox_agent(
        self,
        agent_id: str,
        agent_config: dict[str, Any],
        session_name: str,
        project_path: Path,
        prompt: str,
        window_label: str,
        role: str | None,
    ) -> bool:
        sandbox_name = f"{agent_id}-{project_path.name}"
        sandbox = self.sandbox_mgr.create_sandbox(
            name=sandbox_name,
            agent_id=agent_id,
            project_path=str(project_path),
        )
        if not sandbox:
            return False

        cmd = self._agent_command(agent_id, agent_config, prompt)
        docker_cmd = f"docker exec -it agentbox-{sandbox_name} {cmd}"
        window_name = self.tmux_mgr.add_agent_window(
            session_name, f"sb-{window_label}", docker_cmd, str(project_path)
        )
        if not window_name:
            return False

        register_window(
            session_name=session_name,
            window_name=window_name,
            agent_id=agent_id,
            role=role,
            project_path=str(project_path),
            project_name=project_path.name,
            sandbox=True,
            prompt=prompt,
        )
        console.print(Panel(
            f"[green]Agent started in sandbox[/green]\n\n"
            f"Agent: [cyan]{agent_id}[/cyan]\n"
            f"Session: [cyan]{session_name}[/cyan]\n"
            f"Window: [cyan]{window_name}[/cyan]\n"
            f"Container: [cyan]{sandbox.get('name', '')}[/cyan]",
            title="Ask Workflow",
            border_style="blue",
        ))
        return True

    def _agent_command(self, agent_id: str, agent_config: dict[str, Any], prompt: str) -> str:
        run_cmd = agent_config.get("run_cmd", agent_id)
        quoted = shlex.quote(prompt)
        if agent_id == "claude":
            return f"{run_cmd} -p {quoted}"
        if agent_id == "aider":
            return f"{run_cmd} --message {quoted}"
        return f"{run_cmd} {quoted}"

    def _run_git(self, args: list[str], project_path: str | Path) -> subprocess.CompletedProcess[str]:
        cmd = ["git", *args]
        try:
            return subprocess.run(
                cmd,
                cwd=str(Path(project_path).expanduser().resolve()),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                cmd,
                124,
                "",
                "git command timed out after 30 seconds",
            )
