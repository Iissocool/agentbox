"""Tmux manager - create and manage tmux sessions for agent windows."""

import os
import subprocess
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()


class TmuxManager:
    """Manages tmux sessions with agent windows."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.tmux_config = config.get("tmux", {})
        self.session_prefix = self.tmux_config.get("session_prefix", "ag-")
        self.default_shell = self.tmux_config.get("default_shell", "/bin/bash")

    def _tmux_available(self) -> bool:
        """Check if tmux is available."""
        try:
            result = subprocess.run(
                ["tmux", "-V"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _session_name(self, project_name: str) -> str:
        """Get the full tmux session name."""
        return f"{self.session_prefix}{project_name}"

    def _sanitize_name(self, name: str) -> str:
        """Sanitize a name for tmux (no dots allowed)."""
        return name.replace(".", "_").replace(":", "_")

    def session_exists(self, session_name: str) -> bool:
        """Check if a tmux session exists."""
        try:
            result = subprocess.run(
                ["tmux", "has-session", "-t", session_name],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def create_session(self, project_name: str, project_path: str | None = None) -> str:
        """Create a new tmux session for a project.

        Returns the session name.
        """
        if not self._tmux_available():
            console.print("[red]tmux is not installed![/red]")
            console.print("[dim]Install with: brew install tmux[/dim]")
            return ""

        session_name = self._sanitize_name(self._session_name(project_name))

        if self.session_exists(session_name):
            console.print(f"[yellow]Session already exists:[/yellow] {session_name}")
            return session_name

        cmd = ["tmux", "new-session", "-d", "-s", session_name]
        if project_path:
            cmd.extend(["-c", project_path])

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            # Rename the default window
            subprocess.run(
                ["tmux", "rename-window", "-t", f"{session_name}:0", "shell"],
                capture_output=True,
                text=True,
            )
            console.print(f"[green]✓ Session created:[/green] {session_name}")
            return session_name
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Failed to create session: {e.stderr}[/red]")
            return ""

    def add_agent_window(
        self,
        session_name: str,
        agent_id: str,
        command: str,
        project_path: str | None = None,
    ) -> str:
        """Add a new window for an agent in a session.

        Returns the window name.
        """
        window_name = self._sanitize_name(agent_id)

        cmd = ["tmux", "new-window", "-t", session_name, "-n", window_name]
        if project_path:
            cmd.extend(["-c", project_path])

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            # Send the agent command
            if command:
                self._send_literal_command(f"{session_name}:{window_name}", command)
            console.print(f"[green]✓ Window added:[/green] {window_name} in {session_name}")
            return window_name
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Failed to add window: {e.stderr}[/red]")
            return ""

    def add_agent_pane(
        self,
        session_name: str,
        window_name: str,
        agent_id: str,
        command: str,
        project_path: str | None = None,
    ) -> bool:
        """Split a window into panes for side-by-side agents."""
        target = f"{session_name}:{window_name}"

        cmd = ["tmux", "split-window", "-t", target, "-h"]
        if project_path:
            cmd.extend(["-c", project_path])

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            if command:
                self._send_literal_command(target, command)
            return True
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Failed to split pane: {e.stderr}[/red]")
            return False

    def attach_session(self, session_name: str) -> int:
        """Attach to a tmux session.

        If already inside tmux, uses switch-client to avoid nesting.
        Otherwise uses attach-session normally.
        """
        try:
            if os.environ.get("TMUX"):
                # Already inside tmux — switch client instead of nesting
                console.print(
                    f"[dim]Already inside tmux — switching to {session_name} "
                    f"(Ctrl+B then ( to switch back)[/dim]"
                )
                result = subprocess.run(
                    ["tmux", "switch-client", "-t", session_name]
                )
                if result.returncode != 0:
                    console.print(
                        f"[yellow]switch-client failed. Try manually:[/yellow]\n"
                        f"  tmux switch-client -t {session_name}\n"
                        f"  tmux attach-session -t {session_name}"
                    )
                return result.returncode
            result = subprocess.run(["tmux", "attach-session", "-t", session_name])
            if result.returncode != 0:
                console.print(
                    f"[yellow]attach failed. Try manually:[/yellow]\n"
                    f"  tmux attach-session -t {session_name}"
                )
            return result.returncode
        except FileNotFoundError:
            console.print("[red]tmux not found[/red]")
            return 1

    def kill_session(self, session_name: str) -> bool:
        """Kill a tmux session."""
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", session_name],
                capture_output=True,
                text=True,
                check=True,
            )
            console.print(f"[green]✓ Session killed:[/green] {session_name}")
            return True
        except subprocess.CalledProcessError:
            console.print(f"[red]Failed to kill session: {session_name}[/red]")
            return False

    def list_sessions(self) -> list[dict[str, str]]:
        """List all agentbox tmux sessions."""
        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}|#{session_windows}|#{session_attached}"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return []

            sessions = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                name = parts[0]
                # Only show agentbox sessions
                if name.startswith(self.session_prefix):
                    sessions.append({
                        "name": name,
                        "windows": parts[1] if len(parts) > 1 else "?",
                        "attached": "Yes" if (len(parts) > 2 and parts[2] == "1") else "No",
                    })
            return sessions
        except FileNotFoundError:
            return []

    def list_windows(self, session_name: str) -> list[dict[str, str]]:
        """List all windows in a session."""
        try:
            result = subprocess.run(
                ["tmux", "list-windows", "-t", session_name, "-F", "#{window_index}|#{window_name}|#{window_active}"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return []

            windows = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                windows.append({
                    "index": parts[0],
                    "name": parts[1],
                    "active": "Yes" if (len(parts) > 2 and parts[2] == "1") else "No",
                })
            return windows
        except FileNotFoundError:
            return []

    def send_keys(self, session_name: str, window_name: str, keys: str) -> bool:
        """Send keys to a tmux window."""
        target = f"{session_name}:{window_name}"
        return self._send_literal_command(target, keys)

    def _send_literal_command(self, target: str, command: str) -> bool:
        """Type a shell command into tmux literally, then press Enter."""
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "-l", command],
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                capture_output=True,
                text=True,
                check=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def capture_pane(self, session_name: str, window_name: str, lines: int = 50) -> str:
        """Capture the content of a tmux pane."""
        target = f"{session_name}:{window_name}"
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", target, "-p", "-S", f"-{lines}"],
                capture_output=True,
                text=True,
            )
            return result.stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""

    def print_sessions(self) -> None:
        """Print a formatted table of agentbox sessions."""
        sessions = self.list_sessions()
        if not sessions:
            console.print("[dim]No agentbox sessions running.[/dim]")
            return

        table = Table(title="Agentbox Tmux Sessions")
        table.add_column("Session", style="cyan")
        table.add_column("Windows", style="green")
        table.add_column("Attached", style="magenta")

        for s in sessions:
            table.add_row(s["name"], s["windows"], s["attached"])

        console.print(table)

    def print_windows(self, session_name: str) -> None:
        """Print a formatted table of windows in a session."""
        windows = self.list_windows(session_name)
        if not windows:
            console.print(f"[dim]No windows in {session_name}[/dim]")
            return

        table = Table(title=f"Windows in {session_name}")
        table.add_column("#", style="dim")
        table.add_column("Name", style="cyan")
        table.add_column("Active", style="green")

        for w in windows:
            table.add_row(w["index"], w["name"], w["active"])

        console.print(table)
