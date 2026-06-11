"""Agent runner - orchestrates agent execution in sandboxes or local tmux."""

import os
import shlex
import shutil
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
    """Orchestrates running AI agents locally or in Docker sandboxes."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.sandbox_mgr = SandboxManager(config)
        self.tmux_mgr = TmuxManager(config)

    def run_agent(
        self,
        agent_id: str,
        project_path: str | None = None,
        prompt: str | None = None,
        use_sandbox: bool = True,
        attach: bool = True,
        role: str | None = None,
    ) -> bool:
        """Run a single agent in tmux (sandboxed by default).

        Args:
            agent_id: The agent to run (e.g., 'claude', 'codex')
            project_path: Path to the project directory
            prompt: Optional prompt to send to the agent
            use_sandbox: Whether to run in a Docker sandbox (default: True)
            attach: Whether to attach to the tmux session
            role: Optional role label (e.g., 'planner', 'coder')

        Returns:
            True if successful
        """
        agent_config = get_agent_config(self.config, agent_id)
        if not agent_config:
            console.print(f"[red]Unknown agent: {agent_id}[/red]")
            console.print(f"[dim]Available: {', '.join(self.config.get('agents', {}).keys())}[/dim]")
            return False

        # Resolve project path
        if not project_path:
            project_path = os.getcwd()
        project_name = Path(project_path).name

        # Create tmux session
        session_name = self.tmux_mgr.create_session(project_name, project_path)
        if not session_name:
            return False

        # Determine window name: role-agent or just agent
        display_role = role or agent_id
        window_label = f"{display_role}-{agent_id}" if role else agent_id

        if use_sandbox:
            # Check Docker availability before attempting sandbox
            if not self.sandbox_mgr._docker_available():
                console.print("[yellow]⚠ Docker is not available or not running.[/yellow]")
                console.print("[dim]Falling back to local mode. Start Docker to use sandbox.[/dim]")
                use_sandbox = False
            else:
                return self._run_in_sandbox(
                    agent_id, agent_config, session_name, project_path, prompt, attach, role, window_label
                )

        return self._run_local(
            agent_id, agent_config, session_name, project_path, prompt, attach, role, window_label
        )

    def _run_local(
        self,
        agent_id: str,
        agent_config: dict[str, Any],
        session_name: str,
        project_path: str,
        prompt: str | None,
        attach: bool,
        role: str | None,
        window_label: str,
    ) -> bool:
        """Run an agent locally in a tmux window."""
        run_cmd = agent_config.get("run_cmd", agent_id)

        # Check if agent is installed locally
        cli_name = agent_config.get("cli", agent_id)
        if not shutil.which(cli_name):
            console.print(f"[yellow]⚠ '{cli_name}' not found locally.[/yellow]")
            console.print(f"[dim]Install with: {agent_config.get('install_cmd', 'N/A')}[/dim]")
            console.print(f"[dim]Start Docker to use sandbox mode, or install the agent locally.[/dim]")
            return False

        cmd = self._build_agent_command(agent_id, run_cmd, prompt)

        # Add agent window to tmux session
        window_name = self.tmux_mgr.add_agent_window(
            session_name, window_label, cmd, project_path
        )

        if not window_name:
            return False

        # Register in state
        register_window(
            session_name=session_name,
            window_name=window_name,
            agent_id=agent_id,
            role=role,
            project_path=project_path,
            project_name=Path(project_path).name,
            sandbox=False,
            prompt=prompt,
        )

        # Build info panel
        role_info = f"Role:    [yellow]{role}[/yellow]\n" if role else ""
        console.print(Panel(
            f"[green]🚀 {agent_config.get('name', agent_id)} started![/green]\n\n"
            f"Session: [cyan]{session_name}[/cyan]\n"
            f"Window:  [cyan]{window_name}[/cyan]\n"
            f"Path:    [dim]{project_path}[/dim]\n"
            f"Mode:    [magenta]local[/magenta]\n"
            f"{role_info}",
            title=f"Agent: {agent_id}" + (f" ({role})" if role else ""),
            border_style="green",
        ))

        if attach:
            console.print("[dim]Attaching to tmux session... (Ctrl+B then D to detach)[/dim]")
            self.tmux_mgr.attach_session(session_name)

        return True

    def _run_in_sandbox(
        self,
        agent_id: str,
        agent_config: dict[str, Any],
        session_name: str,
        project_path: str,
        prompt: str | None,
        attach: bool,
        role: str | None,
        window_label: str,
    ) -> bool:
        """Run an agent inside a Docker sandbox with tmux."""
        sandbox_name = f"{agent_id}-{Path(project_path).name}"
        sandbox = self.sandbox_mgr.create_sandbox(
            name=sandbox_name,
            agent_id=agent_id,
            project_path=project_path,
        )

        if not sandbox:
            return False

        # Build the run command for docker exec
        run_cmd = agent_config.get("run_cmd", agent_id)
        cmd = self._build_agent_command(agent_id, run_cmd, prompt)

        # Add a tmux window that connects to the sandbox
        docker_cmd = f"docker exec -it agentbox-{sandbox_name} {cmd}"
        window_name = self.tmux_mgr.add_agent_window(
            session_name, f"sb-{window_label}", docker_cmd, project_path
        )

        if not window_name:
            return False

        # Register in state
        register_window(
            session_name=session_name,
            window_name=window_name,
            agent_id=agent_id,
            role=role,
            project_path=project_path,
            project_name=Path(project_path).name,
            sandbox=True,
            prompt=prompt,
        )

        role_info = f"Role:     [yellow]{role}[/yellow]\n" if role else ""
        console.print(Panel(
            f"[green]🚀 {agent_config.get('name', agent_id)} started in sandbox![/green]\n\n"
            f"Session:  [cyan]{session_name}[/cyan]\n"
            f"Window:   [cyan]{window_name}[/cyan]\n"
            f"Container:[cyan]{sandbox.get('name', 'N/A')}[/cyan]\n"
            f"Path:     [dim]{project_path}[/dim]\n"
            f"Mode:     [magenta]sandbox[/magenta]\n"
            f"{role_info}",
            title=f"Agent: {agent_id}" + (f" ({role})" if role else ""),
            border_style="blue",
        ))

        if attach:
            console.print("[dim]Attaching to tmux session... (Ctrl+B then D to detach)[/dim]")
            self.tmux_mgr.attach_session(session_name)

        return True

    def run_compose(
        self,
        composition: list[dict[str, str]],
        project_path: str | None = None,
        prompt: str | None = None,
        use_sandbox: bool = True,
        attach: bool = True,
    ) -> bool:
        """Run a dynamic composition of agent:role pairs.

        Args:
            composition: List of dicts with 'agent' and 'role' keys
                e.g. [{"agent": "codex", "role": "planner"}, {"agent": "claude", "role": "coder"}]
        """
        if not project_path:
            project_path = os.getcwd()
        project_name = Path(project_path).name

        # Create tmux session
        session_name = self.tmux_mgr.create_session(project_name, project_path)
        if not session_name:
            return False

        # Summary panel
        roles_str = ", ".join(f"{c['role']}→{c['agent']}" for c in composition)
        console.print(Panel(
            f"[green]🚀 Starting composed team[/green]\n\n"
            f"Composition: [cyan]{roles_str}[/cyan]\n"
            f"Session: [cyan]{session_name}[/cyan]\n"
            f"Project: [dim]{project_path}[/dim]\n"
            f"Mode: {'sandbox' if use_sandbox else 'local'}",
            title="✨ Compose",
            border_style="yellow",
        ))

        for comp in composition:
            agent_id = comp["agent"]
            role = comp["role"]
            agent_config = get_agent_config(self.config, agent_id)

            if not agent_config:
                console.print(f"[red]Unknown agent: {agent_id}, skipping[/red]")
                continue

            # Use role-specific prompt if available, otherwise use the shared prompt
            role_prompt = comp.get("prompt", prompt)

            window_label = f"{role}-{agent_id}"

            if use_sandbox:
                sandbox_name = f"{agent_id}-{project_name}"
                sandbox = self.sandbox_mgr.create_sandbox(
                    name=sandbox_name,
                    agent_id=agent_id,
                    project_path=project_path,
                )
                if not sandbox:
                    console.print(f"[yellow]⚠ Skipping {agent_id} as '{role}' (sandbox failed)[/yellow]")
                    continue
                run_cmd = agent_config.get("run_cmd", agent_id)
                agent_cmd = self._build_agent_command(agent_id, run_cmd, role_prompt)
                cmd = f"docker exec -it agentbox-{sandbox_name} {agent_cmd}"
                window_name = self.tmux_mgr.add_agent_window(
                    session_name, f"sb-{window_label}", cmd, project_path
                )
            else:
                cli_name = agent_config.get("cli", agent_id)
                if not shutil.which(cli_name):
                    console.print(f"[yellow]⚠ Skipping {agent_id} as '{role}' (not installed locally)[/yellow]")
                    continue

                run_cmd = agent_config.get("run_cmd", agent_id)
                cmd = self._build_agent_command(agent_id, run_cmd, role_prompt)

                window_name = self.tmux_mgr.add_agent_window(
                    session_name, window_label, cmd, project_path
                )

            if window_name:
                register_window(
                    session_name=session_name,
                    window_name=window_name,
                    agent_id=agent_id,
                    role=role,
                    project_path=project_path,
                    project_name=project_name,
                    sandbox=use_sandbox,
                    prompt=role_prompt,
                )

        if attach:
            console.print("[dim]Attaching to tmux session... (Ctrl+B then D to detach)[/dim]")
            self.tmux_mgr.attach_session(session_name)

        return True

    def run_team(
        self,
        team_id: str,
        project_path: str | None = None,
        prompt: str | None = None,
        use_sandbox: bool = True,
        attach: bool = True,
    ) -> bool:
        """Run a team of agents in a single tmux session."""
        team_config = get_team_config(self.config, team_id)
        if not team_config:
            console.print(f"[red]Unknown team: {team_id}[/red]")
            console.print(f"[dim]Available: {', '.join(self.config.get('teams', {}).keys())}[/dim]")
            return False

        if not project_path:
            project_path = os.getcwd()
        project_name = Path(project_path).name

        # Create tmux session
        session_name = self.tmux_mgr.create_session(project_name, project_path)
        if not session_name:
            return False

        agents = team_config.get("agents", [])
        console.print(Panel(
            f"[green]🚀 Starting team: {team_config.get('description', team_id)}[/green]\n\n"
            f"Agents: {[a.get('role', a.get('agent', '?')) for a in agents]}\n"
            f"Session: [cyan]{session_name}[/cyan]\n"
            f"Mode: {'sandbox' if use_sandbox else 'local'}",
            title=f"Team: {team_id}",
            border_style="yellow",
        ))

        for i, agent_def in enumerate(agents):
            agent_id = agent_def.get("agent", "")
            role = agent_def.get("role", agent_id)
            agent_prompt = agent_def.get("prompt", prompt)

            agent_config = get_agent_config(self.config, agent_id)
            if not agent_config:
                console.print(f"[red]Unknown agent in team: {agent_id}[/red]")
                continue

            window_label = f"{role}-{agent_id}"

            if use_sandbox:
                sandbox_name = f"{agent_id}-{project_name}"
                sandbox = self.sandbox_mgr.create_sandbox(
                    name=sandbox_name,
                    agent_id=agent_id,
                    project_path=project_path,
                )
                if not sandbox:
                    console.print(f"[yellow]⚠ Skipping {agent_id} as '{role}' (sandbox failed)[/yellow]")
                    continue
                run_cmd = agent_config.get("run_cmd", agent_id)
                agent_cmd = self._build_agent_command(agent_id, run_cmd, agent_prompt)
                cmd = f"docker exec -it agentbox-{sandbox_name} {agent_cmd}"
                window_name = self.tmux_mgr.add_agent_window(
                    session_name, f"sb-{window_label}", cmd, project_path
                )
            else:
                cli_name = agent_config.get("cli", agent_id)
                if not shutil.which(cli_name):
                    console.print(f"[yellow]⚠ Skipping {agent_id} as '{role}' (not installed locally)[/yellow]")
                    continue

                run_cmd = agent_config.get("run_cmd", agent_id)
                cmd = self._build_agent_command(agent_id, run_cmd, agent_prompt)

                window_name = self.tmux_mgr.add_agent_window(
                    session_name, window_label, cmd, project_path
                )

            if window_name:
                register_window(
                    session_name=session_name,
                    window_name=window_name,
                    agent_id=agent_id,
                    role=role,
                    project_path=project_path,
                    project_name=project_name,
                    sandbox=use_sandbox,
                    prompt=agent_prompt,
                )

        if attach:
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
        if not project_path:
            project_path = os.getcwd()
        project_name = Path(project_path).name

        session_name = self.tmux_mgr.create_session(project_name, project_path)
        if not session_name:
            return False

        if not prompt:
            prompt = "Hello! Help me with this project."

        # First agent gets its own window
        first_agent = agent_ids[0]
        first_config = get_agent_config(self.config, first_agent)
        if not first_config:
            console.print(f"[red]Unknown agent: {first_agent}[/red]")
            return False

        run_cmd = first_config.get("run_cmd", first_agent)
        cmd = self._build_agent_command(first_agent, run_cmd, prompt)
        window_name = self.tmux_mgr.add_agent_window(
            session_name, f"compare-{first_agent}", cmd, project_path
        )

        if window_name:
            register_window(
                session_name=session_name,
                window_name=window_name,
                agent_id=first_agent,
                role="compare",
                project_path=project_path,
                project_name=project_name,
                prompt=prompt,
            )

        # Subsequent agents split into panes
        for agent_id in agent_ids[1:]:
            agent_config = get_agent_config(self.config, agent_id)
            if not agent_config:
                console.print(f"[yellow]⚠ Unknown agent: {agent_id}, skipping[/yellow]")
                continue

            cli_name = agent_config.get("cli", agent_id)
            if not shutil.which(cli_name):
                console.print(f"[yellow]⚠ {agent_id} not installed, skipping[/yellow]")
                continue

            run_cmd = agent_config.get("run_cmd", agent_id)
            cmd = self._build_agent_command(agent_id, run_cmd, prompt)
            self.tmux_mgr.add_agent_pane(
                session_name, window_name, agent_id, cmd, project_path
            )

        console.print(Panel(
            f"[green]🚀 Compare mode: {len(agent_ids)} agents[/green]\n\n"
            f"Agents:  [cyan]{', '.join(agent_ids)}[/cyan]\n"
            f"Prompt:  [dim]{prompt[:80]}...[/dim]\n"
            f"Session: [cyan]{session_name}[/cyan]",
            title="Compare Mode",
            border_style="magenta",
        ))

        self.tmux_mgr.attach_session(session_name)
        return True

    def list_available_agents(self) -> None:
        """Print a table of all configured agents and their local availability."""
        agents = self.config.get("agents", {})
        local_agents = detect_local_agents()
        local_ids = {a["id"] for a in local_agents}

        table = Table(title="Available AI Agents")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Type", style="magenta")
        table.add_column("Installed", style="bold")
        table.add_column("Install Command", style="dim", max_width=50)

        for agent_id, agent_config in agents.items():
            installed = "✅" if agent_id in local_ids else "❌"
            table.add_row(
                agent_id,
                agent_config.get("name", agent_id),
                agent_config.get("type", "cli"),
                installed,
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
