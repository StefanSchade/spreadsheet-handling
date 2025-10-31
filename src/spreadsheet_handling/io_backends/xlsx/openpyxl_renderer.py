from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.styles import Font


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def _area_to_ref(r1: int, c1: int, r2: int, c2: int) -> str:
    c1l = get_column_letter(c1)
    c2l = get_column_letter(c2)
    if r1 == r2 and c1 == c2:
        return f"{c1l}{r1}"
    return f"{c1l}{r1}:{c2l}{r2}"


def _get_ws(wb: Workbook, name: str) -> Worksheet:
    if name in wb.sheetnames:
        return wb[name]
    return wb.create_sheet(title=name)


def _write(ws: Worksheet, row: int, col: int, value: Any) -> None:
    ws.cell(row=row, column=col, value=value)


# --------------------------------------------------------------------------------------
# IR path (legacy)
#   Expects an object with attribute `sheets: Dict[str, SheetIR]`
#   where each SheetIR may have .validations like list[{kind, area, formula, allow_empty}]
# --------------------------------------------------------------------------------------

def _render_from_ir(ir: Any, out_path: Path) -> None:
    wb = Workbook()
    default = wb.active
    wb.remove(default)

    # sheets
    for name, sheet_ir in getattr(ir, "sheets", {}).items():
        ws = _get_ws(wb, name)

        # optional validations in IR form
        for dv_spec in getattr(sheet_ir, "validations", []) or []:
            if getattr(dv_spec, "kind", None) == "list":
                area = getattr(dv_spec, "area", None)
                formula = getattr(dv_spec, "formula", None)
                allow = bool(getattr(dv_spec, "allow_empty", True))
                if area and formula:
                    r1, c1, r2, c2 = area
                    dv = DataValidation(type="list", formula1=formula, allow_blank=allow)
                    ws.add_data_validation(dv)
                    dv.add(_area_to_ref(r1, c1, r2, c2))

    wb.save(out_path)

# --------------------------------------------------------------------------------------
# RenderPlan path (new)
#   Duck-typed executor that understands common ops used in P1:
#   - DefineSheet(sheet, order?)
#   - SetHeader(sheet, row, col, text)
#   - SetCell/WriteCell(sheet, row, col, value)
#   - AddValidation(kind='list', sheet, col, values, from_row, to_row)
#   - FreezeBelowHeader / AutoFilter (optional if present)
#   - AddMetaSheet(meta: dict, hidden=True)  (ignored except sheet creation)
# --------------------------------------------------------------------------------------

def _render_from_plan(plan: Any, out_path: Path) -> None:
    wb = Workbook()
    default = wb.active
    wb.remove(default)

    sheets_order: list[str] = list(getattr(plan, "sheet_order", []) or [])
    defined: set[str] = set()

    # First pass: create sheets deterministically (DefineSheet or from order list)
    for op in getattr(plan, "ops", []) or []:
        name = type(op).__name__
        if name == "DefineSheet":
            sheet = getattr(op, "sheet", None)
            if sheet and sheet not in defined:
                _get_ws(wb, sheet)
                defined.add(sheet)

    for s in sheets_order:
        if s and s not in defined:
            _get_ws(wb, s)
            defined.add(s)

    if not defined:
        # Fallback: ensure at least one sheet exists for smoke tests
        _get_ws(wb, "Sheet1")

    # Second pass: execute operations
    for op in getattr(plan, "ops", []) or []:
        oname = type(op).__name__

        # Headers
        if oname == "SetHeader":
            sheet = getattr(op, "sheet", None)
            row = int(getattr(op, "row", 1))
            col = int(getattr(op, "col", 1))
            text = getattr(op, "text", "")
            if sheet:
                ws = _get_ws(wb, sheet)
                _write(ws, row, col, text)
            continue

        # Generic cell write
        if oname in {"SetCell", "WriteCell"}:
            sheet = getattr(op, "sheet", None)
            row = int(getattr(op, "row", 1))
            col = int(getattr(op, "col", 1))
            val = getattr(op, "value", "")
            if sheet:
                ws = _get_ws(wb, sheet)
                _write(ws, row, col, val)
            continue

        # Freeze panes (if present)
        if oname in {"FreezeBelowHeader", "FreezePane"}:
            sheet = getattr(op, "sheet", None)
            row = int(getattr(op, "row", 2))
            col = int(getattr(op, "col", 1))
            if sheet:
                ws = _get_ws(wb, sheet)
                ws.freeze_panes = f"{get_column_letter(col)}{row}"
            continue

        # AutoFilter (if present)
        if oname in {"SetAutoFilter", "AutoFilter"}:
            sheet = getattr(op, "sheet", None)
            if sheet:
                ws = _get_ws(wb, sheet)
                try:
                    ws.auto_filter.ref = ws.dimensions  # e.g. "A1:C2"
                except Exception:
                    pass
            continue

        # Data validation (list)
        if (
                "Validation" in oname
                or getattr(op, "kind", None) == "list"
                or hasattr(op, "values")
                or hasattr(op, "formula")
        ):
            sheet = getattr(op, "sheet", None)
            if not sheet:
                continue
            ws = _get_ws(wb, sheet)

            # area calculation
            if all(hasattr(op, x) for x in ("r1", "c1", "r2", "c2")):
                r1, c1, r2, c2 = int(op.r1), int(op.c1), int(op.r2), int(op.c2)
            elif hasattr(op, "area"):
                r1, c1, r2, c2 = map(int, op.area)
            else:
                col = int(getattr(op, "col", 1))
                r1 = int(getattr(op, "from_row", 2))
                r2 = int(getattr(op, "to_row", r1))
                r1, c1, r2, c2 = r1, col, r2, col

            ref = _area_to_ref(r1, c1, r2, c2)
            formula = getattr(op, "formula", None)
            if not formula:
                values = list(getattr(op, "values", []) or [])
                if not values:
                    continue
                formula = f'"{",".join(map(str, values))}"'
            allow = bool(getattr(op, "allow_empty", True))

            # ensure the validation is properly linked to the sheet
            dv = DataValidation(type="list", formula1=formula, allow_blank=allow)
            dv.add(ref)
            if ws.data_validations is None or dv not in ws.data_validations.dataValidation:
                ws.add_data_validation(dv)

            print(f"✅ Added DV to {sheet}:{ref} -> {formula}")
            continue

        # WriteMeta: write key/value pairs to the given (possibly hidden) sheet
        if oname == "WriteMeta":
            sheet = getattr(op, "sheet", None) or "_meta"
            kv = getattr(op, "kv", {}) or {}
            hidden = bool(getattr(op, "hidden", False))
            ws = _get_ws(wb, sheet)
            # Write each key/value pair into two columns
            row = 1
            for k, v in kv.items():
                ws.cell(row=row, column=1, value=str(k))
                ws.cell(row=row, column=2, value=str(v))
                row += 1
            if hidden:
                ws.sheet_state = "hidden"
            print(f"✅ Wrote meta: {len(kv)} items to {sheet}")
            continue

        # DefineSheet (already handled for creation)
        if oname == "DefineSheet":
            continue

        # AddMetaSheet (we only ensure the sheet exists; content optional for P1)
        if oname in {"AddMetaSheet", "DefineHiddenSheet"}:
            sheet = getattr(op, "sheet", None) or getattr(op, "name", None)
            if sheet:
                _get_ws(wb, sheet)
            continue

        # Unknown op -> ignore (smoke path)
        # print(f"[xlsx renderer] skipping op {oname}")

    # --- P1 parity: default header styling (bold row 1) ---
    for ws in wb.worksheets:
        if ws.max_column:
            for j in range(1, ws.max_column + 1):
                cell = ws.cell(row=1, column=j)
                if cell.value not in (None, ""):
                    # preserve existing attrs, just force bold
                    cell.font = Font(name=cell.font.name, size=cell.font.size, bold=True)

    # --- P1 parity: apply default freeze pane and autofilter if requested ---
    for ws in wb.worksheets:
        if not ws.freeze_panes:
            ws.freeze_panes = "A2"
        if not ws.auto_filter.ref and ws.max_row and ws.max_column:
            ws.auto_filter.ref = ws.dimensions

    wb.save(out_path)

# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------

def render_workbook(obj: Any, out_path: Path | str) -> None:
    """
    Render either:
      - IR object with `.sheets` (legacy), or
      - RenderPlan object with `.ops` (new).
    """
    out_path = Path(out_path)

    if hasattr(obj, "sheets"):
        _render_from_ir(obj, out_path)
        return

    if hasattr(obj, "ops"):
        _render_from_plan(obj, out_path)
        return

    raise TypeError("render_workbook: unsupported object; expected IR (.sheets) or RenderPlan (.ops)")


# Historical alias used by early IR smoke tests.
def render_plan(plan: Any, out_path: Path | str) -> None:
    """
    Deprecated: prefer render_workbook(plan, out_path).
    Kept temporarily for experimental tests.
    """
    render_workbook(plan, out_path)


__all__ = ["render_workbook", "render_plan"]
