"""Tmux session lifecycle management — creating, attaching, and orchestrating
per-agent windows and panes so that each agentbox project runs in its own
isolated terminal multiplexer workspace."""

import os
import subprocess
import sys
import time
from typing import Any

from rich.console import Console
from rich.table import Table


# ── Module State ────────────────────────────────────

console = Console()


# ── Tmux Manager ────────────────────────────────────


class TmuxManager:
    """Manages tmux sessions with agent windows."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the manager from the application config.

        Parameters:
            config: Top-level agentbox configuration dictionary.  The
                ``"tmux"`` key (if present) may override the session
                prefix and default shell.
        """
        self.config = config
        self.tmux_config = config.get("tmux", {})
        self.session_prefix = self.tmux_config.get("session_prefix", "ag-")
        self.default_shell = self.tmux_config.get("default_shell", "/bin/bash")

    # ── Private Helpers ─────────────────────────────

    def _tmux_available(self) -> bool:
        """Check whether tmux is installed and reachable on ``$PATH``.

        Returns:
            ``True`` if ``tmux -V`` exits successfully within five
            seconds; ``False`` otherwise.
        """
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
        """Build the full tmux session name for a project.

        Parameters:
            project_name: Bare project identifier (without prefix).

        Returns:
            The prefixed session name string.
        """
        return f"{self.session_prefix}{project_name}"

    def _sanitize_name(self, name: str) -> str:
        """Sanitize a name so tmux accepts it (dots and colons are illegal).

        Parameters:
            name: Raw name that may contain forbidden characters.

        Returns:
            A sanitized copy with ``.`` and ``:`` replaced by ``_``.
        """
        return name.replace(".", "_").replace(":", "_")

    # ── Session Lifecycle ───────────────────────────

    def session_exists(self, session_name: str) -> bool:
        """Check whether a tmux session is currently alive.

        Parameters:
            session_name: Fully-qualified session name (with prefix).

        Returns:
            ``True`` if the session exists; ``False`` otherwise.
        """
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

        If the session already exists its ``default-path`` is updated when
        *project_path* is provided, and the existing name is returned.

        Parameters:
            project_name: Human-readable project identifier.
            project_path: Working directory for the session.  When
                ``None`` tmux uses the caller's cwd.

        Returns:
            The session name on success, or an empty string on failure.
        """
        if not self._tmux_available():
            console.print("[red]tmux is not installed![/red]")
            console.print("[dim]Install with: brew install tmux[/dim]")
            return ""

        session_name = self._sanitize_name(self._session_name(project_name))

        if self.session_exists(session_name):
            console.print(f"[dim]Session already exists: {session_name}[/dim]")
            if project_path:
                try:
                    subprocess.run(
                        ["tmux", "set-option", "-t", session_name, "default-path", project_path],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                except Exception:
                    pass
            return session_name

        cmd = ["tmux", "new-session", "-d", "-s", session_name]
        if project_path:
            cmd.extend(["-c", project_path])

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
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

    def kill_session(self, session_name: str) -> bool:
        """Kill a tmux session and all of its windows.

        Parameters:
            session_name: Fully-qualified session name to destroy.

        Returns:
            ``True`` if the session was killed; ``False`` on error.
        """
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

    def attach_session(self, session_name: str, window_name: str | None = None) -> int:
        """Attach to (or switch into) a tmux session.

        Uses ``subprocess.run`` so that after detaching (``Ctrl+B D``)
        control returns to the caller — e.g. the REPL.

        Terminal state is carefully managed: the terminal is restored from
        raw mode (left by *prompt_toolkit*) before attaching, and again
        after detaching.

        Parameters:
            session_name: Fully-qualified session name.
            window_name: Optional window to select before attaching.

        Returns:
            The ``returncode`` from the tmux subprocess, or ``1`` on
            error.
        """
        try:
            os.system("stty sane 2>/dev/null")
            time.sleep(0.1)

            if window_name:
                subprocess.run(
                    ["tmux", "select-window", "-t", f"{session_name}:{window_name}"],
                    capture_output=True,
                    text=True,
                    check=False,
                )

            if os.environ.get("TMUX"):
                result = subprocess.run(["tmux", "switch-client", "-t", session_name])
            else:
                result = subprocess.run(["tmux", "attach-session", "-t", session_name])

            os.system("stty sane 2>/dev/null")
            time.sleep(0.05)
            return result.returncode

        except FileNotFoundError:
            console.print("[red]tmux not found[/red]")
            return 1
        except Exception as e:
            os.system("stty sane 2>/dev/null")
            console.print(f"[red]Failed to attach: {e}[/red]")
            return 1

    # ── Window & Pane Management ────────────────────

    def add_agent_window(
        self,
        session_name: str,
        agent_id: str,
        command: str,
        project_path: str | None = None,
    ) -> str:
        """Add a new window for an agent inside an existing session.

        Parameters:
            session_name: Fully-qualified session name.
            agent_id: Identifier used as the window title (sanitized).
            command: Shell command to send once the window is created.
            project_path: Working directory for the new window.

        Returns:
            The window name on success, or an empty string on failure.
        """
        window_name = self._sanitize_name(agent_id)

        cmd = ["tmux", "new-window", "-t", session_name, "-n", window_name]
        if project_path:
            cmd.extend(["-c", project_path])

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
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
        """Split a window into panes for side-by-side agents.

        Parameters:
            session_name: Fully-qualified session name.
            window_name: Target window to split.
            agent_id: Identifier for the new pane (used in logging).
            command: Shell command to send once the pane is created.
            project_path: Working directory for the new pane.

        Returns:
            ``True`` if the pane was created; ``False`` on error.
        """
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

    # ── Input & Capture ─────────────────────────────

    def send_keys(self, session_name: str, window_name: str, keys: str) -> bool:
        """Send keystrokes to a tmux window.

        Parameters:
            session_name: Fully-qualified session name.
            window_name: Target window within the session.
            keys: Literal text to type into the pane.

        Returns:
            ``True`` if the keys were sent; ``False`` on error.
        """
        target = f"{session_name}:{window_name}"
        return self._send_literal_command(target, keys)

    def _send_literal_command(self, target: str, command: str) -> bool:
        """Type a shell command into tmux literally, then press Enter.

        Parameters:
            target: tmux target spec (``session:window``).
            command: Raw text to send via ``send-keys -l``.

        Returns:
            ``True`` on success; ``False`` on error.
        """
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
        """Capture the visible content of a tmux pane.

        Parameters:
            session_name: Fully-qualified session name.
            window_name: Target window within the session.
            lines: Number of lines of scrollback to include.

        Returns:
            The pane content as a string, or an empty string on error.
        """
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

    # ── Introspection ───────────────────────────────

    def list_sessions(self) -> list[dict[str, str]]:
        """List all agentbox-managed tmux sessions.

        Only sessions whose names start with the configured prefix are
        included.

        Returns:
            A list of dicts with keys ``"name"``, ``"windows"``, and
            ``"attached"``.
        """
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
        """List all windows in a tmux session.

        Parameters:
            session_name: Fully-qualified session name.

        Returns:
            A list of dicts with keys ``"index"``, ``"name"``, and
            ``"active"``.
        """
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

    # ── Display ─────────────────────────────────────

    def print_sessions(self) -> None:
        """Print a rich-formatted table of agentbox sessions."""
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
        """Print a rich-formatted table of windows in a session.

        Parameters:
            session_name: Fully-qualified session name.
        """
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
