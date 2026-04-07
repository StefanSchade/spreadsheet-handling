from __future__ import annotations

from pathlib import Path

from spreadsheet_handling.rendering.ir import WorkbookIR
from spreadsheet_handling.rendering.parse_ir import parse_ir


def parse_workbook(path: str | Path) -> WorkbookIR:
    """Parse an XLSX workbook into ``WorkbookIR`` via openpyxl."""
    return parse_ir(Path(path))


__all__ = ['parse_workbook']
