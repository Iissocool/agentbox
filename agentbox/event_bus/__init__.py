"""Event Bus — unified system event collection and distribution.

Collects events from agents, Docker, tmux, and pipelines,
then distributes them to subscribers (ui_gateway, ui-agent).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import Any, Callable, Coroutine

from rich.console import Console

console = Console()


# ── Event Data Structures ──────────────────────────────────


class Event:
    """A single system event."""

    __slots__ = ("type", "source", "data", "timestamp")

    def __init__(
        self,
        type: str,
        source: str,
        data: dict[str, Any] | None = None,
        timestamp: float | None = None,
    ):
        self.type = type
        self.source = source
        self.data = data or {}
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "source": self.source,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


# ── Subscriber Protocol ────────────────────────────────────


# Type alias for async callback
AsyncCallback = Callable[[Event], Coroutine[Any, Any, None]]
SyncCallback = Callable[[Event], None]


# ── Event Bus ──────────────────────────────────────────────


class EventBus:
    """Singleton event bus for system-wide event distribution.

    Usage:
        bus = EventBus.get()
        bus.subscribe("agent_event", my_callback)
        bus.publish(Event("agent_event", "runner", {"agent": "claude", "event": "started"}))
    """

    _instance: EventBus | None = None

    def __init__(self) -> None:
        self._subscribers: dict[str, list[AsyncCallback | SyncCallback]] = defaultdict(list)
        self._global_subscribers: list[AsyncCallback | SyncCallback] = []
        self._history: list[Event] = []
        self._max_history = 500

    @classmethod
    def get(cls) -> EventBus:
        """Get the singleton EventBus instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    # ── Subscribe ──────────────────────────────────────

    def subscribe(self, event_type: str, callback: AsyncCallback | SyncCallback) -> None:
        """Subscribe to events of a specific type."""
        self._subscribers[event_type].append(callback)

    def subscribe_all(self, callback: AsyncCallback | SyncCallback) -> None:
        """Subscribe to all events."""
        self._global_subscribers.append(callback)

    def unsubscribe(self, event_type: str, callback: AsyncCallback | SyncCallback) -> None:
        """Unsubscribe from a specific event type."""
        subs = self._subscribers.get(event_type, [])
        if callback in subs:
            subs.remove(callback)

    def unsubscribe_all(self, callback: AsyncCallback | SyncCallback) -> None:
        """Unsubscribe a callback from all event types and global subscribers."""
        if callback in self._global_subscribers:
            self._global_subscribers.remove(callback)
        for subs in self._subscribers.values():
            if callback in subs:
                subs.remove(callback)

    # ── Publish ────────────────────────────────────────

    def publish(self, event: Event) -> None:
        """Publish an event synchronously to all subscribers."""
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        # Type-specific subscribers
        for callback in self._subscribers.get(event.type, []):
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    # Schedule coroutine if we're in an async context
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(result)
                    except RuntimeError:
                        # No running loop, run synchronously
                        asyncio.run(result)
            except Exception as exc:
                console.print(f"[dim]Event callback error: {exc}[/dim]")

        # Global subscribers
        for callback in self._global_subscribers:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(result)
                    except RuntimeError:
                        asyncio.run(result)
            except Exception as exc:
                console.print(f"[dim]Global callback error: {exc}[/dim]")

    async def publish_async(self, event: Event) -> None:
        """Publish an event asynchronously."""
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        for callback in self._subscribers.get(event.type, []):
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                console.print(f"[dim]Event callback error: {exc}[/dim]")

        for callback in self._global_subscribers:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                console.print(f"[dim]Global callback error: {exc}[/dim]")

    # ── History ────────────────────────────────────────

    def get_history(self, event_type: str | None = None, limit: int = 50) -> list[Event]:
        """Get recent events, optionally filtered by type."""
        if event_type:
            events = [e for e in self._history if e.type == event_type]
        else:
            events = self._history
        return events[-limit:]

    def get_history_dicts(self, event_type: str | None = None, limit: int = 50) -> list[dict]:
        """Get recent events as dicts."""
        return [e.to_dict() for e in self.get_history(event_type, limit)]


# ── Convenience Functions ──────────────────────────────────


def emit(type: str, source: str, data: dict[str, Any] | None = None) -> None:
    """Quick-emit an event to the singleton bus."""
    EventBus.get().publish(Event(type, source, data))


async def emit_async(type: str, source: str, data: dict[str, Any] | None = None) -> None:
    """Quick-emit an event asynchronously."""
    await EventBus.get().publish_async(Event(type, source, data))