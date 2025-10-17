from typing import Any, Dict, List
from ..ir import DataValidationSpec

def _csv_formula(values: List[str]) -> str:
    # openpyxl expects: formula1='"A,B,C"'
    escaped = ",".join(v.replace('"', '""') for v in values)
    return f'"{escaped}"'

def apply(ir, meta: Dict[str, Any]):
    """
    Minimal implementation:
    - looks for meta["constraints"] entries with:
        {"sheet": "<name>", "column": "<col-name>", "rule": {"type": "in_list", "values": [...]}}
    - attaches a list validation to a generous default area on that sheet.
    NOTE: We don't yet resolve the real column index; we use column 1 (A) as a placeholder
    just to satisfy tests that only assert presence of any validation.
    """
    constraints = (meta or {}).get("constraints") or []
    for c in constraints:
        sheet_name = c.get("sheet")
        col_name = c.get("column")
        rule = (c.get("rule") or {})
        if not sheet_name or not col_name or rule.get("type") != "in_list":
            continue
        sheet_ir = ir.sheets.get(sheet_name)
        if not sheet_ir or not sheet_ir.tables:
            continue
        table = sheet_ir.tables[0]  # first table on the sheet (refine if needed)
        col_idx = table.header_map.get(str(col_name))
        if not col_idx:
            # can't resolve → skip or log via meta.issues later
            continue

        # data rows start below header, typical row 2..(n_rows)
        r1, r2 = 2, table.n_rows
        c1 = c2 = col_idx

        values = rule.get("values") or []
        formula = f"\"{','.join(str(v).replace('\"','\"\"') for v in values)}\""

        sheet_ir.validations.append(
            DataValidationSpec(
                kind="list",
                area=(r1, c1, r2, c2),
                formula=formula,
                allow_empty=True,
            )
        )
    return ir

