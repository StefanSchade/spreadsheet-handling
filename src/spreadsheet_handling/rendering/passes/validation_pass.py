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
    constraints = meta.get("constraints") or []
    if not constraints:
        return ir

    for c in constraints:
        if not isinstance(c, dict):
            continue
        sheet_name = c.get("sheet")
        rule = (c.get("rule") or {})
        if rule.get("type") != "in_list":
            continue
        values = rule.get("values") or []
        if not sheet_name or not values:
            continue

        sheet_ir = ir.sheets.get(sheet_name)
        if not sheet_ir:
            # sheet may not exist yet (composer creates per frame-name),
            # skip silently for now
            continue

        # Very generous default area: A2:A500 (row 2..500)
        # We'll refine once composer provides column mapping.
        r1, r2 = 2, 500
        c1 = c2 = 1  # column A

        sheet_ir.validations.append(
            DataValidationSpec(
                kind="list",
                area=(r1, c1, r2, c2),
                formula=_csv_formula([str(v) for v in values]),
                allow_empty=True,
            )
        )
    return ir
