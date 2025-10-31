from __future__ import annotations
from typing import Protocol
from spreadsheet_handling.rendering.plan import RenderPlan

class XlsxBackend(Protocol):
    """
    Protocol for XLSX-capable backends. Implementations translate a RenderPlan
    into a concrete .xlsx workbook and write it to disk.
    """
    def render(self, plan: RenderPlan, output_path: str) -> None: ...
