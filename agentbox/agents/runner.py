"""Agent runner - orchestrates agent execution in Docker sandboxes."""

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..config import detect_local_agents, get_agent_config, get_team_config
from ..sandbox import SandboxManager
from ..state import register_window, unregister_session
from ..tmux_mgr import TmuxManager

console = Console()


class AgentRunner:
    """Orchestrates running AI agents in Docker sandboxes."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.sandbox_mgr = SandboxManager(config)
        self.tmux_mgr = TmuxManager(config)

    def _window_exists(self, session_name: str, window_name: str) -> bool:
        """Check if a tmux window exists in a session."""
        windows = self.tmux_mgr.list_windows(session_name)
        return any(w["name"] == window_name for w in windows)

    def _window_process_alive(self, session_name: str, window_name: str) -> bool:
        """Check if the process in a tmux window is still running (not at shell prompt)."""
        try:
            content = self.tmux_mgr.capture_pane(session_name, window_name, lines=5)
            # If the pane shows a shell prompt, the process is dead
            lines = content.strip().split("\n")
            if not lines:
                return False
            last_line = lines[-1].strip()
            # Shell prompt patterns: ends with $ or # or ❯ or >
            if last_line.endswith(("$", "#", "❯", ">")) and len(last_line) < 80:
                return False
            # If pane is empty, process is dead
            if not last_line:
                return False
            return True
        except Exception:
            return False

    def _restart_window(self, session_name: str, window_name: str, command: str) -> bool:
        """Restart the command in an existing tmux window."""
        try:
            target = f"{session_name}:{window_name}"
            # Send Ctrl+C to kill any running process, then clear
            subprocess.run(["tmux", "send-keys", "-t", target, "C-c"],
                          capture_output=True, text=True)
            time.sleep(0.3)
            # Clear the line and send the new command
            subprocess.run(["tmux", "send-keys", "-t", target, "C-u"],
                          capture_output=True, text=True)
            self.tmux_mgr._send_literal_command(target, command)
            console.print(f"[green]✓ Restarted agent in window:[/green] {window_name}")
            return True
        except Exception as e:
            console.print(f"[red]Failed to restart window: {e}[/red]")
            return False

    def run_agent(
        self,
        agent_id: str,
        project_path: str | None = None,
        prompt: str | None = None,
        attach: bool = True,
        role: str | None = None,
        with_shell: bool = False,
    ) -> bool:
        """Run a single agent in a Docker sandbox via tmux."""
        agent_config = get_agent_config(self.config, agent_id)
        if not agent_config:
            console.print(f"[red]Unknown agent: {agent_id}[/red]")
            console.print(f"[dim]Available: {', '.join(self.config.get('agents', {}).keys())}[/dim]")
            return False

        if not self.sandbox_mgr._docker_available():
            console.print("[red]✘ Docker is not available or not running![/red]")
            console.print("[dim]Agentbox requires Docker to run agents in sandboxes.[/dim]")
            console.print("[dim]Start Docker Desktop or Docker daemon first.[/dim]")
            return False

        if not project_path:
            project_path = os.getcwd()
        project_name = Path(project_path).name

        session_name = self.tmux_mgr.create_session(project_name, project_path)
        if not session_name:
            return False

        display_role = role or agent_id
        window_label = f"{display_role}-{agent_id}" if role else agent_id
        window_name = self.tmux_mgr._sanitize_name(f"sb-{window_label}")

        sandbox_name = f"{agent_id}-{project_name}"

        # ── Check if agent window already exists and is alive ──
        if self._window_exists(session_name, window_name):
            if self._window_process_alive(session_name, window_name):
                console.print(f"[green]✓ Agent '{agent_id}' is already running in {session_name}:{window_name}[/green]")
                if attach:
                    console.print("[dim]Attaching to tmux session... (Ctrl+B then D to detach)[/dim]")
                    self.tmux_mgr.attach_session(session_name, window_name=window_name)
                return True
            else:
                # Process is dead — restart it
                console.print(f"[yellow]⚠ Agent '{agent_id}' window exists but process is dead, restarting...[/yellow]")
                sandbox = self.sandbox_mgr.create_sandbox(
                    name=sandbox_name, agent_id=agent_id, project_path=project_path,
                )
                if not sandbox:
                    return False
                run_cmd = agent_config.get("run_cmd", agent_id)
                cmd = self._build_agent_command(agent_id, run_cmd, prompt)
                docker_cmd = self._build_docker_exec(agent_id, f"agentbox-{sandbox_name}", cmd)
                self._restart_window(session_name, window_name, docker_cmd)

                register_window(
                    session_name=session_name, window_name=window_name,
                    agent_id=agent_id, role=role, project_path=project_path,
                    project_name=project_name, sandbox=True, prompt=prompt,
                )

                if attach:
                    time.sleep(0.3)
                    console.print("[dim]Attaching to tmux session... (Ctrl+B then D to detach)[/dim]")
                    self.tmux_mgr.attach_session(session_name, window_name=window_name)
                return True

        # ── Create new sandbox + agent window ──
        sandbox = self.sandbox_mgr.create_sandbox(
            name=sandbox_name, agent_id=agent_id, project_path=project_path,
        )
        if not sandbox:
            return False

        run_cmd = agent_config.get("run_cmd", agent_id)
        cmd = self._build_agent_command(agent_id, run_cmd, prompt)
        docker_cmd = self._build_docker_exec(agent_id, f"agentbox-{sandbox_name}", cmd)
        new_window_name = self.tmux_mgr.add_agent_window(
            session_name, f"sb-{window_label}", docker_cmd, project_path
        )
        if not new_window_name:
            return False
        window_name = new_window_name

        register_window(
            session_name=session_name, window_name=window_name,
            agent_id=agent_id, role=role, project_path=project_path,
            project_name=project_name, sandbox=True, prompt=prompt,
        )

        # Add companion shell if requested
        if with_shell:
            self.add_companion_shell(
                agent_id, session_name, sandbox_name,
                project_path, project_name,
            )

        role_info = f"Role:      [yellow]{role}[/yellow]\n" if role else ""
        shell_info = f"Shell:     [green]shell-{agent_id}[/green] (Ctrl+B n/p 切换)\n" if with_shell else ""
        console.print(Panel(
            f"[green]🚀 {agent_config.get('name', agent_id)} started in sandbox![/green]\n\n"
            f"Session:   [cyan]{session_name}[/cyan]\n"
            f"Window:    [cyan]{window_name}[/cyan]\n"
            f"Container: [cyan]{sandbox.get('name', 'N/A')}[/cyan]\n"
            f"Path:      [dim]{project_path}[/dim]\n"
            f"Mode:      [magenta]sandbox[/magenta]\n"
            f"{shell_info}{role_info}",
            title=f"Agent: {agent_id}" + (f" ({role})" if role else ""),
            border_style="blue",
        ))

        if attach:
            # Brief pause to let the agent command initialize in tmux
            # before attaching (avoids terminal state corruption on first run)
            time.sleep(0.5)
            console.print("[dim]Attaching to tmux session... (Ctrl+B then D to detach)[/dim]")
            self.tmux_mgr.attach_session(session_name, window_name=window_name)

        return True

    def run_compose(
        self,
        composition: list[dict[str, str]],
        project_path: str | None = None,
        prompt: str | None = None,
        attach: bool = True,
    ) -> bool:
        """Run a dynamic composition of agent:role pairs in sandboxes."""
        if not self.sandbox_mgr._docker_available():
            console.print("[red]✘ Docker is not available or not running![/red]")
            return False

        if not project_path:
            project_path = os.getcwd()
        project_name = Path(project_path).name

        session_name = self.tmux_mgr.create_session(project_name, project_path)
        if not session_name:
            return False

        roles_str = ", ".join(f"{c['role']}→{c['agent']}" for c in composition)
        console.print(Panel(
            f"[green]🚀 Starting composed team[/green]\n\n"
            f"Composition: [cyan]{roles_str}[/cyan]\n"
            f"Session: [cyan]{session_name}[/cyan]\n"
            f"Project: [dim]{project_path}[/dim]\n"
            f"Mode: sandbox",
            title="✨ Compose", border_style="yellow",
        ))

        for comp in composition:
            agent_id = comp["agent"]
            role = comp["role"]
            agent_config = get_agent_config(self.config, agent_id)
            if not agent_config:
                console.print(f"[red]Unknown agent: {agent_id}, skipping[/red]")
                continue

            role_prompt = comp.get("prompt", prompt)
            window_label = f"{role}-{agent_id}"

            sandbox_name = f"{agent_id}-{project_name}"
            sandbox = self.sandbox_mgr.create_sandbox(
                name=sandbox_name, agent_id=agent_id, project_path=project_path,
            )
            if not sandbox:
                console.print(f"[yellow]⚠ Skipping {agent_id} as '{role}' (sandbox failed)[/yellow]")
                continue

            run_cmd = agent_config.get("run_cmd", agent_id)
            agent_cmd = self._build_agent_command(agent_id, run_cmd, role_prompt)
            cmd = self._build_docker_exec(agent_id, f"agentbox-{sandbox_name}", agent_cmd)
            window_name = self.tmux_mgr.add_agent_window(
                session_name, f"sb-{window_label}", cmd, project_path
            )
            if window_name:
                register_window(
                    session_name=session_name, window_name=window_name,
                    agent_id=agent_id, role=role, project_path=project_path,
                    project_name=project_name, sandbox=True, prompt=role_prompt,
                )

        if attach:
            time.sleep(0.3)
            console.print("[dim]Attaching to tmux session... (Ctrl+B then D to detach)[/dim]")
            self.tmux_mgr.attach_session(session_name)
        return True

    def run_team(
        self,
        team_id: str,
        project_path: str | None = None,
        prompt: str | None = None,
        attach: bool = True,
    ) -> bool:
        """Run a team of agents in Docker sandboxes."""
        if not self.sandbox_mgr._docker_available():
            console.print("[red]✘ Docker is not available or not running![/red]")
            return False

        team_config = get_team_config(self.config, team_id)
        if not team_config:
            console.print(f"[red]Unknown team: {team_id}[/red]")
            console.print(f"[dim]Available: {', '.join(self.config.get('teams', {}).keys())}[/dim]")
            return False

        if not project_path:
            project_path = os.getcwd()
        project_name = Path(project_path).name

        session_name = self.tmux_mgr.create_session(project_name, project_path)
        if not session_name:
            return False

        agents = team_config.get("agents", [])
        console.print(Panel(
            f"[green]🚀 Starting team: {team_config.get('description', team_id)}[/green]\n\n"
            f"Agents: {[a.get('role', a.get('agent', '?')) for a in agents]}\n"
            f"Session: [cyan]{session_name}[/cyan]\n"
            f"Mode: sandbox",
            title=f"Team: {team_id}", border_style="yellow",
        ))

        for agent_def in agents:
            agent_id = agent_def.get("agent", "")
            role = agent_def.get("role", agent_id)
            agent_prompt = agent_def.get("prompt", prompt)
            agent_config = get_agent_config(self.config, agent_id)
            if not agent_config:
                console.print(f"[red]Unknown agent in team: {agent_id}[/red]")
                continue

            window_label = f"{role}-{agent_id}"
            sandbox_name = f"{agent_id}-{project_name}"
            sandbox = self.sandbox_mgr.create_sandbox(
                name=sandbox_name, agent_id=agent_id, project_path=project_path,
            )
            if not sandbox:
                console.print(f"[yellow]⚠ Skipping {agent_id} as '{role}' (sandbox failed)[/yellow]")
                continue

            run_cmd = agent_config.get("run_cmd", agent_id)
            agent_cmd = self._build_agent_command(agent_id, run_cmd, agent_prompt)
            cmd = self._build_docker_exec(agent_id, f"agentbox-{sandbox_name}", agent_cmd)
            window_name = self.tmux_mgr.add_agent_window(
                session_name, f"sb-{window_label}", cmd, project_path
            )
            if window_name:
                register_window(
                    session_name=session_name, window_name=window_name,
                    agent_id=agent_id, role=role, project_path=project_path,
                    project_name=project_name, sandbox=True, prompt=agent_prompt,
                )

        if attach:
            time.sleep(0.3)
            console.print("[dim]Attaching to tmux session... (Ctrl+B then D to detach)[/dim]")
            self.tmux_mgr.attach_session(session_name)
        return True

    def run_compare(
        self,
        agent_ids: list[str],
        project_path: str | None = None,
        prompt: str | None = None,
    ) -> bool:
        """Run the same prompt on multiple agents side by side for comparison."""
        if not self.sandbox_mgr._docker_available():
            console.print("[red]✘ Docker is not available or not running![/red]")
            return False

        if not project_path:
            project_path = os.getcwd()
        project_name = Path(project_path).name

        session_name = self.tmux_mgr.create_session(project_name, project_path)
        if not session_name:
            return False

        if not prompt:
            prompt = "Hello! Help me with this project."

        first_agent = agent_ids[0]
        first_config = get_agent_config(self.config, first_agent)
        if not first_config:
            console.print(f"[red]Unknown agent: {first_agent}[/red]")
            return False

        sandbox_name = f"{first_agent}-{project_name}"
        sandbox = self.sandbox_mgr.create_sandbox(
            name=sandbox_name, agent_id=first_agent, project_path=project_path,
        )
        if not sandbox:
            return False

        run_cmd = first_config.get("run_cmd", first_agent)
        cmd = self._build_agent_command(first_agent, run_cmd, prompt)
        docker_cmd = self._build_docker_exec(first_agent, f"agentbox-{sandbox_name}", cmd)
        window_name = self.tmux_mgr.add_agent_window(
            session_name, f"compare-{first_agent}", docker_cmd, project_path
        )
        if window_name:
            register_window(
                session_name=session_name, window_name=window_name,
                agent_id=first_agent, role="compare", project_path=project_path,
                project_name=project_name, sandbox=True, prompt=prompt,
            )

        for agent_id in agent_ids[1:]:
            agent_config = get_agent_config(self.config, agent_id)
            if not agent_config:
                console.print(f"[yellow]⚠ Unknown agent: {agent_id}, skipping[/yellow]")
                continue

            sb_name = f"{agent_id}-{project_name}"
            sb = self.sandbox_mgr.create_sandbox(
                name=sb_name, agent_id=agent_id, project_path=project_path,
            )
            if not sb:
                console.print(f"[yellow]⚠ Skipping {agent_id} (sandbox failed)[/yellow]")
                continue

            run_cmd = agent_config.get("run_cmd", agent_id)
            cmd = self._build_agent_command(agent_id, run_cmd, prompt)
            docker_cmd = self._build_docker_exec(agent_id, f"agentbox-{sb_name}", cmd)
            self.tmux_mgr.add_agent_pane(
                session_name, window_name, agent_id, docker_cmd, project_path
            )

        console.print(Panel(
            f"[green]🚀 Compare mode: {len(agent_ids)} agents in sandbox[/green]\n\n"
            f"Agents:  [cyan]{', '.join(agent_ids)}[/cyan]\n"
            f"Prompt:  [dim]{prompt[:80]}...[/dim]\n"
            f"Session: [cyan]{session_name}[/cyan]",
            title="Compare Mode", border_style="magenta",
        ))

        time.sleep(0.3)
        self.tmux_mgr.attach_session(session_name)
        return True

    def run_shell(
        self,
        agent_id: str,
        project_path: str | None = None,
        attach: bool = True,
    ) -> bool:
        """Open a bash shell in an agent's sandbox container.

        If the agent's sandbox exists, opens a shell in it.
        If not, creates the sandbox first, then opens a shell.
        The shell window is added to the agent's existing tmux session
        (or a new one is created).
        """
        if not self.sandbox_mgr._docker_available():
            console.print("[red]✘ Docker is not available or not running![/red]")
            return False

        if not project_path:
            project_path = os.getcwd()
        project_name = Path(project_path).name

        sandbox_name = f"{agent_id}-{project_name}"
        container_name = f"agentbox-{sandbox_name}"

        # Ensure sandbox exists and is running
        sandbox = self.sandbox_mgr.create_sandbox(
            name=sandbox_name, agent_id=agent_id, project_path=project_path,
        )
        if not sandbox:
            return False

        # Find or create tmux session
        session_name = self.tmux_mgr.create_session(project_name, project_path)
        if not session_name:
            return False

        # Check if shell window already exists
        shell_window_name = self.tmux_mgr._sanitize_name(f"shell-{agent_id}")
        if self._window_exists(session_name, shell_window_name):
            console.print(f"[green]✓ Shell for '{agent_id}' already exists in {session_name}:{shell_window_name}[/green]")
            if attach:
                console.print("[dim]Attaching to tmux session... (Ctrl+B then D to detach, Ctrl+B n/p switch windows)[/dim]")
                self.tmux_mgr.attach_session(session_name)
            return True

        # Create shell window: docker exec -it <container> bash
        mount_point = self.config.get("sandbox", {}).get("mount_point", "/workspace")
        shell_cmd = self._build_docker_exec(agent_id, container_name, "bash")
        new_window_name = self.tmux_mgr.add_agent_window(
            session_name, f"shell-{agent_id}", shell_cmd, project_path
        )

        if new_window_name:
            register_window(
                session_name=session_name, window_name=new_window_name,
                agent_id=agent_id, role="shell", project_path=project_path,
                project_name=project_name, sandbox=True, prompt=None,
            )

        console.print(Panel(
            f"[green]🐚 Shell opened for {agent_id} sandbox![/green]\n\n"
            f"Session:   [cyan]{session_name}[/cyan]\n"
            f"Window:    [cyan]{new_window_name or shell_window_name}[/cyan]\n"
            f"Container: [cyan]{container_name}[/cyan]\n"
            f"Path:      [dim]{mount_point}[/dim]\n\n"
            f"[dim]Ctrl+B n  下一个窗口 (agent)[/dim]\n"
            f"[dim]Ctrl+B p  上一个窗口[/dim]\n"
            f"[dim]Ctrl+B D  脱离会话[/dim]",
            title=f"Shell: {agent_id}",
            border_style="green",
        ))

        if attach:
            time.sleep(0.3)
            console.print("[dim]Attaching to tmux session...[/dim]")
            self.tmux_mgr.attach_session(session_name, window_name=new_window_name or shell_window_name)

        return True

    def add_companion_shell(
        self,
        agent_id: str,
        session_name: str,
        sandbox_name: str,
        project_path: str,
        project_name: str,
    ) -> str | None:
        """Add a companion shell window for an agent in the same tmux session.

        This allows the user to quickly switch between the agent CLI
        and a bash shell in the same container using Ctrl+B n/p.
        """
        shell_window_name = self.tmux_mgr._sanitize_name(f"shell-{agent_id}")

        # Don't create if already exists
        if self._window_exists(session_name, shell_window_name):
            return shell_window_name

        container_name = f"agentbox-{sandbox_name}"
        shell_cmd = self._build_docker_exec(agent_id, container_name, "bash")

        new_window_name = self.tmux_mgr.add_agent_window(
            session_name, f"shell-{agent_id}", shell_cmd, project_path
        )

        if new_window_name:
            register_window(
                session_name=session_name, window_name=new_window_name,
                agent_id=agent_id, role="shell", project_path=project_path,
                project_name=project_name, sandbox=True, prompt=None,
            )

        return new_window_name

    def list_available_agents(self) -> None:
        """Print a table of all configured agents and their local availability."""
        agents = self.config.get("agents", {})
        local_agents = detect_local_agents()
        local_ids = {a["id"] for a in local_agents}

        table = Table(title="Available AI Agents")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Type", style="magenta")
        table.add_column("Installed Locally", style="bold")
        table.add_column("Install Command", style="dim", max_width=50)

        for agent_id, agent_config in agents.items():
            installed = "✅" if agent_id in local_ids else "❌"
            table.add_row(
                agent_id, agent_config.get("name", agent_id),
                agent_config.get("type", "cli"), installed,
                agent_config.get("install_cmd", ""),
            )
        console.print(table)

    def _build_agent_command(self, agent_id: str, run_cmd: str, prompt: str | None = None) -> str:
        """Build a shell-safe agent command."""
        if not prompt:
            return run_cmd
        quoted = shlex.quote(prompt)
        if agent_id == "claude":
            return f"{run_cmd} -p {quoted}"
        if agent_id == "aider":
            return f"{run_cmd} --message {quoted}"
        return f"{run_cmd} {quoted}"

    def _build_docker_exec(self, agent_id: str, container_name: str, command: str) -> str:
        """Build a clean docker exec command (no env injection)."""
        return f"docker exec -it {container_name} {command}"
