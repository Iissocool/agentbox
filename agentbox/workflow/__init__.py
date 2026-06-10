"""Workflow engine - complete ask -> sandbox -> agent -> diff -> merge pipeline."""

try:
    from .core import WorkflowEngine
except ImportError:
    WorkflowEngine = None

__all__ = ["WorkflowEngine"]
