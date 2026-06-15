"""Workspace Manager — multi-folder workspace management for Agentbox.

Each workspace is a project folder with its own:
- agents (selected by user)
- pipeline config
- shared context file
- isolated tmux session

Workspaces persist to ~/.agentbox/workspaces.json
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE_DIR = Path.home() / ".agentbox"
WORKSPACE_DB = WORKSPACE_DIR / "workspaces.json"

# Available agents from contracts
AVAILABLE_AGENTS = ["coder", "architect", "reviewer", "codex", "claude", "aider"]

# Available pipeline templates
PIPELINE_TEMPLATES = {
    "dev-pipeline": {"name": "Dev Pipeline", "desc": "Plan → Code → Review", "steps": 3},
    "research-pipeline": {"name": "Research Pipeline", "desc": "Research → Summarize → Critique", "steps": 3},
    "compare-pipeline": {"name": "Compare Pipeline", "desc": "Parallel agents → Synthesize", "steps": 3},
    "single-agent": {"name": "Single Agent", "desc": "One agent, direct task", "steps": 1},
}


def _ensure_db() -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    if not WORKSPACE_DB.exists():
        WORKSPACE_DB.write_text("[]", encoding="utf-8")


def _load_workspaces() -> list[dict[str, Any]]:
    _ensure_db()
    with open(WORKSPACE_DB, encoding="utf-8") as f:
        return json.load(f)


def _save_workspaces(data: list[dict[str, Any]]) -> None:
    _ensure_db()
    with open(WORKSPACE_DB, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def create_workspace(folder_path: str, name: str = "", agents: list[str] | None = None, pipeline: str = "single-agent") -> dict[str, Any]:
    """Create a new workspace from a folder path (drag-drop target)."""
    folder = Path(folder_path).resolve()
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder_path}")

    ws_id = f"ws-{uuid.uuid4().hex[:8]}"
    workspace = {
        "id": ws_id,
        "name": name or folder.name,
        "folder_path": str(folder),
        "agents": agents or ["coder"],
        "pipeline": pipeline,
        "status": "idle",
        "created_at": datetime.now().isoformat(),
        "context_file": str(folder / ".agentbox_context.md"),
        "tmux_session": f"agbox-{ws_id}",
    }

    # Create shared context file
    context_file = folder / ".agentbox_context.md"
    if not context_file.exists():
        context_file.write_text(f"# Agentbox Shared Context — {workspace['name']}\n\n", encoding="utf-8")

    workspaces = _load_workspaces()
    workspaces.append(workspace)
    _save_workspaces(workspaces)

    return workspace


def list_workspaces() -> list[dict[str, Any]]:
    """List all workspaces."""
    return _load_workspaces()


def get_workspace(ws_id: str) -> dict[str, Any] | None:
    """Get a workspace by ID."""
    for ws in _load_workspaces():
        if ws["id"] == ws_id:
            return ws
    return None


def update_workspace(ws_id: str, **kwargs: Any) -> dict[str, Any] | None:
    """Update workspace fields (agents, pipeline, name, status)."""
    workspaces = _load_workspaces()
    for ws in workspaces:
        if ws["id"] == ws_id:
            ws.update(kwargs)
            _save_workspaces(workspaces)
            return ws
    return None


def delete_workspace(ws_id: str) -> bool:
    """Delete a workspace."""
    workspaces = _load_workspaces()
    new_list = [ws for ws in workspaces if ws["id"] != ws_id]
    if len(new_list) < len(workspaces):
        _save_workspaces(new_list)
        return True
    return False


def get_available_agents() -> list[dict[str, str]]:
    """Return list of available agents."""
    return [{"id": a, "name": a.capitalize()} for a in AVAILABLE_AGENTS]


def get_pipeline_templates() -> dict[str, dict[str, Any]]:
    """Return available pipeline templates."""
    return PIPELINE_TEMPLATES