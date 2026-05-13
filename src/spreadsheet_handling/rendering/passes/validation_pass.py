from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from spreadsheet_handling.core.formulas import list_literal_formula

from ._base import (
    DataValidationSpec,
    WorkbookIR,
    _target_validation_columns,
    _validation_values,
    _workbook_meta,
)


@dataclass
class ValidationPass:
    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        # Legacy path: per-sheet _p1_validations (column index based)
        for sh in doc.sheets.values():
            raw: List[Dict[str, Any]] = sh.meta.get("_p1_validations", [])
            for spec in raw:
                if spec.get("kind") != "list":
                    continue
                col = int(spec["col"])
                r1 = int(spec.get("from_row", 2))
                r2 = int(spec.get("to_row", r1))
                values = list(map(str, spec.get("values", [])))
                formula = list_literal_formula(values)
                dv = DataValidationSpec(
                    kind="list", area=(r1, col, r2, col), formula=formula, allow_empty=True
                )
                sh.validations.append(dv)

        # New path: workbook-level constraints (column name based)
        wb_meta = _workbook_meta(doc)
        constraints = wb_meta.get("constraints") or []
        for c in constraints:
            if not isinstance(c, dict):
                continue
            sheet_name = c.get("sheet")
            col_name = c.get("column")
            area = c.get("area")
            rule = c.get("rule") or {}
            if not sheet_name or not isinstance(rule, dict):
                continue
            values = _validation_values(rule, wb_meta)
            if values is None:
                continue
            target = doc.sheets.get(str(sheet_name))
            if not target or not target.tables:
                continue
            t = target.tables[0]
            column_indices = _target_validation_columns(
                t,
                column_name=col_name,
                area=area,
            )
            if not column_indices:
                continue
            r1 = t.top + t.header_rows
            r2 = max(r1, t.top + t.n_rows - 1)
            formula = list_literal_formula(values)
            for col_idx in column_indices:
                dv = DataValidationSpec(
                    kind="list",
                    area=(r1, col_idx, r2, col_idx),
                    formula=formula,
                    allow_empty=True,
                )
                target.validations.append(dv)

        return doc


__all__ = ["ValidationPass"]
