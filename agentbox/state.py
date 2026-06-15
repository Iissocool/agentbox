"""Session state tracker — persists agent/role/project info for each tmux window.

All read-modify-write operations are protected by a POSIX file lock
(``fcntl.flock``) so that concurrent ``ag`` processes do not corrupt the
shared state file at ``~/.agentbox/state.json``.
"""

import fcntl
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()

STATE_FILE = Path.home() / ".agentbox" / "state.json"
_LOCK_FILE = Path.home() / ".agentbox" / "state.json.lock"


# ── File Locking ───────────────────────────────────────


def _ensure_state_dir() -> None:
    """Ensure state directory exists."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


class _StateLock:
    """Simple file-based lock for concurrent access protection.

    Uses ``fcntl.flock`` (POSIX advisory lock) to prevent race conditions
    when multiple ``ag`` processes read/modify/write state simultaneously.
    """

    def __enter__(self):
        _ensure_state_dir()
        self._fd = open(_LOCK_FILE, "w")
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        self._fd.close()


# ── Load / Save ────────────────────────────────────────


def load_state() -> dict[str, Any]:
    """Load the session state from disk."""
    if not STATE_FILE.exists():
        return {"sessions": {}}

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"sessions": {}}


def save_state(state: dict[str, Any]) -> None:
    """Save the session state to disk (with file locking)."""
    with _StateLock():
        _ensure_state_dir()
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)


# ── Registration ───────────────────────────────────────


def register_window(
    session_name: str,
    window_name: str,
    agent_id: str,
    role: str | None = None,
    project_path: str | None = None,
    project_name: str | None = None,
    sandbox: bool = False,
    prompt: str | None = None,
) -> None:
    """Register a window in the session state."""
    with _StateLock():
        state = load_state()

        if session_name not in state["sessions"]:
            state["sessions"][session_name] = {
                "created_at": datetime.now().isoformat(),
                "project_name": project_name or "",
                "project_path": project_path or "",
                "windows": {},
            }

        state["sessions"][session_name]["windows"][window_name] = {
            "agent": agent_id,
            "role": role or agent_id,
            "project_path": project_path or "",
            "sandbox": sandbox,
            "prompt": prompt or "",
            "started_at": datetime.now().isoformat(),
        }

        # Update project info on session level
        if project_name:
            state["sessions"][session_name]["project_name"] = project_name
        if project_path:
            state["sessions"][session_name]["project_path"] = project_path

        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)


def unregister_session(session_name: str) -> None:
    """Remove a session from the state."""
    with _StateLock():
        state = load_state()
        state["sessions"].pop(session_name, None)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)


def unregister_window(session_name: str, window_name: str) -> None:
    """Remove a window from the session state."""
    with _StateLock():
        state = load_state()
        if session_name in state["sessions"]:
            state["sessions"][session_name]["windows"].pop(window_name, None)
            if not state["sessions"][session_name]["windows"]:
                del state["sessions"][session_name]
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)


# ── Queries ────────────────────────────────────────────


def get_session_info(session_name: str) -> dict[str, Any] | None:
    """Get info about a specific session."""
    state = load_state()
    return state["sessions"].get(session_name)


def get_window_info(session_name: str, window_name: str) -> dict[str, Any] | None:
    """Get info about a specific window."""
    state = load_state()
    session = state["sessions"].get(session_name, {})
    return session.get("windows", {}).get(window_name)


def list_all_sessions() -> dict[str, Any]:
    """Get all tracked sessions."""
    state = load_state()
    return state.get("sessions", {})


# ── Cleanup & Recovery ─────────────────────────────────


def cleanup_stale_sessions(active_tmux_sessions: list[str]) -> int:
    """Remove state entries for sessions that no longer exist in tmux.

    Returns the number of cleaned up sessions.
    """
    with _StateLock():
        state = load_state()
        tracked = list(state["sessions"].keys())
        removed = 0

        for session_name in tracked:
            if session_name not in active_tmux_sessions:
                del state["sessions"][session_name]
                removed += 1

        if removed > 0:
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)

    return removed


def cleanup_stale_windows(session_name: str, active_windows: list[str]) -> int:
    """Remove state entries for windows that no longer exist in tmux.

    Returns the number of cleaned up windows.
    """
    with _StateLock():
        state = load_state()
        removed = 0

        if session_name in state["sessions"]:
            windows = state["sessions"][session_name].get("windows", {})
            stale = [w for w in list(windows.keys()) if w not in active_windows]
            for w in stale:
                del windows[w]
                removed += 1
            if not windows:
                del state["sessions"][session_name]
            if removed > 0:
                with open(STATE_FILE, "w") as f:
                    json.dump(state, f, indent=2, ensure_ascii=False)

    return removed


def recover_orphaned_sessions() -> int:
    """Recover sessions that exist in tmux/Docker but not in state.

    Scans for agentbox Docker containers that have no corresponding state
    entry, and recreates the state from labels.

    Returns the number of recovered sessions.
    """
    import subprocess

    with _StateLock():
        state = load_state()
        recovered = 0

        # Find agentbox Docker containers
        try:
            result = subprocess.run(
                ["docker", "ps", "-a",
                 "--filter", "label=agentbox=true",
                 "--format", "{{.Names}}|{{.Labels}}|{{.Status}}"],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                return 0
        except FileNotFoundError:
            return 0

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            parts = line.split("|")
            if len(parts) < 3:
                continue

            container_name = parts[0]
            labels_str = parts[1] if len(parts) > 1 else ""
            status = parts[2] if len(parts) > 2 else ""

            # Parse labels robustly — use index-based lookup for dotted keys
            agent_id = ""
            project_path = ""
            for label in labels_str.split(","):
                if "=" not in label:
                    continue
                k, v = label.split("=", 1)
                if k == "agentbox.agent":
                    agent_id = v
                elif k == "desktop.docker.io/binds/0/Source":
                    project_path = v

            if not agent_id:
                continue

            # Derive session name from container name
            # Container format: agentbox-{agent_id}-{project_name}
            # Session format: ag-{project_name}
            name_without_prefix = container_name.replace("agentbox-", "", 1)
            if name_without_prefix.startswith(f"{agent_id}-"):
                project_name = name_without_prefix[len(agent_id) + 1:]
            else:
                project_name = name_without_prefix

            session_name = f"ag-{project_name}"

            # Check if this session already tracked
            if session_name in state["sessions"]:
                # Check if this window already tracked
                window_name = f"sb-{agent_id}"
                if window_name in state["sessions"][session_name].get("windows", {}):
                    continue
                # Add missing window
                state["sessions"][session_name]["windows"][window_name] = {
                    "agent": agent_id,
                    "role": agent_id,
                    "project_path": "",
                    "sandbox": True,
                    "prompt": "",
                    "started_at": datetime.now().isoformat(),
                    "container": container_name,
                }
                recovered += 1
                continue

            # Create new session entry
            state["sessions"][session_name] = {
                "created_at": datetime.now().isoformat(),
                "project_name": project_name,
                "project_path": project_path,
                "windows": {
                    f"sb-{agent_id}": {
                        "agent": agent_id,
                        "role": agent_id,
                        "project_path": project_path,
                        "sandbox": True,
                        "prompt": "",
                        "started_at": datetime.now().isoformat(),
                        "container": container_name,
                    }
                },
            }
            recovered += 1

        if recovered > 0:
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            console.print(f"[green]♻️ Recovered {recovered} orphaned session(s) from Docker[/green]")

    return recovered
