"""Typed errors for deprecated or unavailable I/O backends."""
from __future__ import annotations


class DeprecatedAdapterError(NotImplementedError):
    """Raised when a deprecated adapter is invoked.

    Attributes:
        adapter: short name of the adapter (e.g. ``"ods"``, ``"xlsxwriter"``).
        hint:    actionable migration guidance shown to the caller.
    """

    def __init__(self, adapter: str, hint: str) -> None:
        self.adapter = adapter
        self.hint = hint
        super().__init__(
            f"Adapter '{adapter}' is deprecated and no longer available. {hint}"
        )
