"""UI Agent — read-only system state projector for macOS menu bar integration.

Subscribes to orchestrator, tmux, docker states via event_bus.
Outputs unified UI State Snapshot as JSON.
Cannot modify files, execute docker mutations, or run shell modifications.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..event_bus import EventBus, Event, emit
from ..state import load_state
from ..config import load_config


# ── System Status Aggregator ───────────────────────────────


class UIStateAggregator:
    """Aggregates system state from multiple sources and event bus."""

    def __init__(self) -> None:
        self._last_events: list[dict] = []
        self._system_health = "ok"

    def get_snapshot(self) -> dict[str, Any]:
        """Produce a unified UI State Snapshot."""
        state = load_state()
        active_agents: list[str] = []
        pipeline_name = ""
        progress = 0.0
        alerts: list[dict[str, str]] = []

        # ── Collect active agents from state ──
        for _sn, sd in state.get("sessions", {}).items():
            for _wn, wd in sd.get("windows", {}).items():
                aid = wd.get("agent", "")
                if aid and aid not in active_agents:
                    active_agents.append(aid)

        status = "idle" if not active_agents else "running"

        # ── Check pipeline state ──
        pd = Path.home() / ".agentbox" / "pipelines"
        if pd.exists():
            for path in sorted(pd.glob("*.json"), reverse=True)[:1]:
                try:
                    with open(path) as f:
                        data = json.load(f)
                    if data.get("status") == "running":
                        pipeline_name = data.get("pipeline_name", "")
                        steps = data.get("steps", {})
                        completed = sum(
                            1 for s in steps.values() if s.get("status") == "completed"
                        )
                        total = len(steps)
                        progress = completed / total if total else 0.0
                        status = "running"
                    elif data.get("status") == "completed":
                        pipeline_name = data.get("pipeline_name", "")
                        progress = 1.0
                except Exception:
                    alerts.append({"level": "warning", "message": f"Corrupt: {path.name}"})

        # ── Check Docker availability ──
        try:
            import docker as docker_lib
            client = docker_lib.from_env()
            client.ping()
        except Exception:
            alerts.append({"level": "error", "message": "Docker not available"})
            self._system_health = "degraded"
            if status == "idle":
                status = "degraded"
        else:
            self._system_health = "ok"

        # ── Get recent events from bus ──
        bus = EventBus.get()
        recent = bus.get_history_dicts(limit=10)
        self._last_events = recent

        return {
            "status": status,
            "active_agents": active_agents,
            "pipeline": pipeline_name,
            "progress": round(progress, 2),
            "system_health": self._system_health,
            "alerts": alerts,
            "recent_events": recent,
            "timestamp": time.time(),
        }


# ── Module-level API (backward compatible) ─────────────────

_aggregator = UIStateAggregator()


def get_system_snapshot() -> dict[str, Any]:
    """Produce a read-only JSON snapshot of the current system state.

    Returns:
        A dictionary with: status, active_agents, pipeline, progress,
        system_health, alerts, recent_events, timestamp.
    """
    return _aggregator.get_snapshot()


def format_snapshot_json(snapshot: dict[str, Any] | None = None) -> str:
    """Format a system snapshot as compact JSON.

    Args:
        snapshot: Pre-computed snapshot. If None, generates a fresh one.

    Returns:
        JSON string suitable for menu bar display.
    """
    if snapshot is None:
        snapshot = get_system_snapshot()
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))


# ── Event Bus Integration ──────────────────────────────────


def _on_agent_event(event: Event) -> None:
    """React to agent events — update internal health tracking."""
    data = event.data
    if data.get("event") == "error":
        _aggregator._system_health = "degraded"
    elif data.get("event") in ("started", "completed"):
        _aggregator._system_health = "ok"


# Auto-subscribe to agent events when module loads
try:
    EventBus.get().subscribe("agent_event", _on_agent_event)
except Exception:
    pass