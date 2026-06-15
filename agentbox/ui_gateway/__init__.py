"""UI Gateway — HTTP/WebSocket server for macOS Menu Bar App integration.

Exposes:
  GET /status       — system status JSON
  GET /events       — recent event history
  WS  /stream       — real-time event stream
  WS  /pipeline     — pipeline status stream
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from typing import Any

from aiohttp import web, WSMsgType
from rich.console import Console

from ..event_bus import EventBus, Event
from ..agents.ui_agent import get_system_snapshot
from ..config import load_config

console = Console()


# ── Default Port ───────────────────────────────────────────

DEFAULT_PORT = 18733


# ── Route Handlers ─────────────────────────────────────────


async def handle_status(request: web.Request) -> web.Response:
    """GET /status — return current system status as JSON."""
    snapshot = get_system_snapshot()
    snapshot["system"] = "agentbox"
    snapshot["timestamp"] = time.time()

    # Enrich with tmux sessions and docker containers
    try:
        from ..tmux_mgr import TmuxManager
        config = load_config()
        tmux = TmuxManager(config)
        snapshot["tmux_sessions"] = tmux.list_sessions()
    except Exception:
        snapshot["tmux_sessions"] = []

    try:
        import docker as docker_lib
        client = docker_lib.from_env()
        containers = client.containers.list(filters={"name": "agentbox-"})
        snapshot["docker_containers"] = [
            {"name": c.name, "status": c.status, "image": str(c.image.tags)}
            for c in containers
        ]
    except Exception:
        snapshot["docker_containers"] = []

    # Pipeline state
    from ..orchestrator.engine import Orchestrator
    runs = Orchestrator.list_pipeline_runs()
    snapshot["running_pipelines"] = [r for r in runs if r.get("status") == "running"]

    return web.json_response(snapshot)


async def handle_events(request: web.Request) -> web.Response:
    """GET /events — return recent event history."""
    bus = EventBus.get()
    event_type = request.query.get("type")
    limit = int(request.query.get("limit", "50"))
    events = bus.get_history_dicts(event_type=event_type, limit=limit)
    return web.json_response({"events": events, "count": len(events)})


async def handle_pipelines(request: web.Request) -> web.Response:
    from ..orchestrator.engine import Orchestrator
    runs = Orchestrator.list_pipeline_runs()
    enriched = []
    for run in runs[:10]:
        detail = Orchestrator.get_pipeline_run(run.get("run_id", ""))
        step_flow, context_keys = [], []
        if detail:
            for sid, res in detail.get("steps", {}).items():
                step_flow.append({"step_id": sid, "status": res.get("status", "?"), "has_output": bool(res.get("output", ""))})
            context_keys = list(detail.get("context_keys", []))
        enriched.append({**run, "step_flow": step_flow, "context_keys": context_keys})
    return web.json_response({"pipelines": enriched, "count": len(enriched)})


async def handle_pipeline_detail(request: web.Request) -> web.Response:
    from ..orchestrator.engine import Orchestrator
    run_id = request.match_info.get("run_id", "")
    data = Orchestrator.get_pipeline_run(run_id)
    if not data:
        return web.json_response({"error": "not found"}, status=404)
    data["step_flow"] = [{"step_id": s, "status": r.get("status", "?"), "has_output": bool(r.get("output", ""))} for s, r in data.get("steps", {}).items()]
    return web.json_response(data)


async def handle_context(request: web.Request) -> web.Response:
    from ..orchestrator.engine import Orchestrator
    run_id = request.match_info.get("run_id", "")
    data = Orchestrator.get_pipeline_run(run_id)
    if not data:
        return web.json_response({"error": "not found"}, status=404)
    steps = data.get("steps", {})
    return web.json_response({"run_id": run_id, "context_keys": data.get("context_keys", []), "step_outputs": {k: {"status": v.get("status"), "len": len(v.get("output", ""))} for k, v in steps.items()}})


async def handle_agent_open(request: web.Request) -> web.Response:
    body = await request.json()
    agent_id = body.get("agent", "")
    if not agent_id:
        return web.json_response({"error": "agent required"}, status=400)
    return web.json_response({"status": "ok", "agent": agent_id})



async def handle_stream(request: web.Request) -> web.WebSocketResponse:
    """WS /stream — real-time event stream to Menu Bar App."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Queue for this subscriber
    queue: asyncio.Queue[Event] = asyncio.Queue()

    async def on_event(event: Event) -> None:
        await queue.put(event)

    bus = EventBus.get()
    bus.subscribe_all(on_event)

    try:
        # Send initial status
        snapshot = get_system_snapshot()
        await ws.send_json({
            "event": "initial_status",
            "data": snapshot,
        })

        # Stream events
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await ws.send_json(event.to_dict())
            except asyncio.TimeoutError:
                # Heartbeat / keep-alive
                await ws.send_json({"event": "heartbeat", "timestamp": time.time()})
    except Exception:
        pass
    finally:
        bus.unsubscribe_all(on_event)

    return ws


async def handle_pipeline(request: web.Request) -> web.WebSocketResponse:
    """WS /pipeline — pipeline-specific status stream."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    queue: asyncio.Queue[Event] = asyncio.Queue()

    async def on_pipeline_event(event: Event) -> None:
        if event.type in ("pipeline_event", "agent_event"):
            await queue.put(event)

    bus = EventBus.get()
    bus.subscribe("pipeline_event", on_pipeline_event)
    bus.subscribe("agent_event", on_pipeline_event)

    try:
        # Send initial pipeline state
        from ..orchestrator.engine import Orchestrator
        runs = Orchestrator.list_pipeline_runs()
        await ws.send_json({
            "event": "pipeline_init",
            "pipelines": runs,
        })

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await ws.send_json(event.to_dict())
            except asyncio.TimeoutError:
                await ws.send_json({"event": "heartbeat", "timestamp": time.time()})
    except Exception:
        pass
    finally:
        bus.unsubscribe("pipeline_event", on_pipeline_event)
        bus.unsubscribe("agent_event", on_pipeline_event)

    return ws


# ── App Factory ────────────────────────────────────────────


def create_app() -> web.Application:
    """Create the aiohttp application with all routes."""
    app = web.Application()
    app.router.add_get("/status", handle_status)
    app.router.add_get("/events", handle_events)
    app.router.add_get("/pipelines", handle_pipelines)
    app.router.add_get("/pipeline/{run_id}", handle_pipeline_detail)
    app.router.add_get("/context/{run_id}", handle_context)
    app.router.add_post("/agent/open", handle_agent_open)
    app.router.add_get("/stream", handle_stream)
    app.router.add_get("/pipeline", handle_pipeline)
    return app


# ── Server Runner ──────────────────────────────────────────


def _gateway_responding(port: int) -> bool:
    """Return True if something is already serving /status on *port*."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


async def _wait_for_shutdown() -> None:
    """Block until cancelled (attach mode when gateway already running)."""
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass


async def run_server(port: int = DEFAULT_PORT) -> None:
    """Run the UI Gateway server."""
    if _gateway_responding(port):
        console.print(
            f"[yellow]Gateway already running on http://localhost:{port}[/yellow]"
        )
        await _wait_for_shutdown()
        return

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    try:
        await site.start()
    except OSError as exc:
        await runner.cleanup()
        if exc.errno == 48 and _gateway_responding(port):
            console.print(
                f"[yellow]Gateway already running on http://localhost:{port}[/yellow]"
            )
            await _wait_for_shutdown()
            return
        raise
    console.print(f"UI Gateway running on http://localhost:{port}")
    try:
        await _wait_for_shutdown()
    finally:
        await runner.cleanup()


def start_gateway(port: int = DEFAULT_PORT) -> None:
    """Start the UI Gateway (blocking)."""
    asyncio.run(run_server(port))


if __name__ == "__main__":
    start_gateway()