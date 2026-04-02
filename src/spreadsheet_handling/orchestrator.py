"""Backward-compatibility shim – the real code now lives in
``spreadsheet_handling.application.orchestrator``.

External consumers that ``import spreadsheet_handling.orchestrator`` or
``from spreadsheet_handling.orchestrator import orchestrate`` will keep
working without changes.
"""
from .application.orchestrator import orchestrate, IODesc  # noqa: F401

__all__ = ["orchestrate", "IODesc"]
