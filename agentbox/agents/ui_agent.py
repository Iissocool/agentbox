"""UI Agent -- read-only system state projector for macOS menu bar."""
from __future__ import annotations
import json
from typing import Any
from ..state import load_state
from ..config import load_config

def get_system_snapshot() -> dict[str, Any]:
    state = load_state()
    active_agents = []
    pipeline_name = ""
    progress = 0.0
    alerts = []
    for sn, sd in state.get("sessions", {}).items():
        for wn, wd in sd.get("windows", {}).items():
            aid = wd.get("agent", "")
            if aid and aid not in active_agents:
                active_agents.append(aid)
    status = "idle" if not active_agents else "running"
    from pathlib import Path
    pd = Path.home() / ".agentbox" / "pipelines"
    if pd.exists():
        for path in sorted(pd.glob("*.json"), reverse=True)[:1]:
            try:
                with open(path) as f: data = json.load(f)
                if data.get("status") == "running":
                    pipeline_name = data.get("pipeline_name", "")
                    steps = data.get("steps", {})
                    completed = sum(1 for s in steps.values() if s.get("status") == "completed")
                    total = len(steps)
                    progress = completed / total if total else 0.0
                    status = "running"
            except Exception:
                alerts.append({"level": "warning", "message": f"Corrupt: {path.name}"})
    try:
        import docker as dl
        dl.from_env().ping()
    except Exception:
        alerts.append({"level": "error", "message": "Docker not available"})
        if status == "idle": status = "degraded"
    return {"status": status, "active_agents": active_agents, "pipeline": pipeline_name, "progress": round(progress, 2), "alerts": alerts}

def format_snapshot_json(snapshot=None):
    if snapshot is None: snapshot = get_system_snapshot()
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
