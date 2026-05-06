"""Spreadsheet backend contract and narrow adapter-facing facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
from spreadsheet_handling.rendering.frame_selection import select_render_frames
from spreadsheet_handling.rendering.flow import build_render_plan
from spreadsheet_handling.rendering.ir import WorkbookIR
from spreadsheet_handling.rendering.passes import apply_all as apply_render_passes
from spreadsheet_handling.rendering.plan import RenderPlan
from spreadsheet_handling.rendering.workbook_projection import workbookir_to_frames


class SpreadsheetRenderer(Protocol):
    """Adapter-specific renderer that executes a backend-neutral ``RenderPlan``."""

    def __call__(self, plan: RenderPlan, output_path: str | Path) -> None: ...


class SpreadsheetParser(Protocol):
    """Format-specific parser that must stop at ``WorkbookIR``."""

    def __call__(self, path: str | Path) -> WorkbookIR: ...


def build_spreadsheet_render_plan(
    frames: Mapping[str, Any],
    meta: Mapping[str, Any] | None,
) -> RenderPlan:
    """Build the spreadsheet-generic ``RenderPlan`` from frames plus canonical meta."""
    meta_dict = dict(meta or {})
    selected_frames = select_render_frames(frames, meta_dict)
    ir = compose_workbook(selected_frames, meta_dict)
    apply_render_passes(ir, meta_dict)
    return build_render_plan(ir)


def read_spreadsheet_frames(
    path: str | Path,
    *,
    parser: SpreadsheetParser,
) -> dict[str, Any]:
    """Parse via a format-specific parser and generically project ``WorkbookIR`` to frames."""
    return workbookir_to_frames(parser(path))


__all__ = [
    'SpreadsheetParser',
    'SpreadsheetRenderer',
    'build_spreadsheet_render_plan',
    'read_spreadsheet_frames',
]
