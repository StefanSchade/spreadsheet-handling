from __future__ import annotations

from typing import Any, Dict, List, Optional
from ..formulas import list_literal_formula
from ..ir import DataValidationSpec
from ..ir import WorkbookIR, SheetIR, TableBlock


def _first_table(sheet: SheetIR) -> Optional[TableBlock]:
    return sheet.tables[0] if sheet.tables else None


def apply(ir: WorkbookIR, meta: Dict[str, Any] | None) -> WorkbookIR:
    """
    Translate domain constraints from meta into DataValidationSpec entries
    on the corresponding SheetIR, using TableBlock.header_map to target the
    correct column.

    Supported rule:
      - {"type": "in_list", "values": [...]}

    Soft-fails: if sheet/column cannot be resolved, no validation is added.
    """
    if not meta:
        return ir

    constraints = meta.get("constraints") or []
    if not isinstance(constraints, list):
        return ir

    for c in constraints:
        if not isinstance(c, dict):
            continue

        sheet_name = c.get("sheet")
        col_name = c.get("column")
        rule = c.get("rule") or {}

        if not sheet_name or not col_name:
            continue
        if rule.get("type") != "in_list":
            # future: extend with other types (e.g., whole-number, custom formula, ranges)
            continue

        sheet_ir = ir.sheets.get(str(sheet_name))
        if not sheet_ir:
            # Unknown sheet -> skip (could log to meta.issues in a separate pass)
            continue

        table = _first_table(sheet_ir)
        if not table:
            continue

        # Resolve the real column index via header_map (1-based)
        col_idx = table.header_map.get(str(col_name))
        if not col_idx:
            # header not found -> skip
            continue

        # Data region: rows 2..n_rows (row 1 is header), column = col_idx
        r1: int = 2
        r2: int = max(2, table.n_rows)  # guard; if empty table.n_rows==1, keep at least 2..2
        c1: int = col_idx
        c2: int = col_idx

        values = rule.get("values") or []
        # normalize to strings; keep stable order
        value_strings: List[str] = [str(v) for v in values]
        formula = list_literal_formula(value_strings)

        sheet_ir.validations.append(
            DataValidationSpec(
                kind="list",
                area=(r1, c1, r2, c2),
                formula=formula,
                allow_empty=True,
            )
        )

    return ir
