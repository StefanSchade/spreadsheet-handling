# src/spreadsheet_handling/steps/validations.py
from __future__ import annotations
from typing import Any, Dict, List

def add_validations(frames, *, rules: List[Dict[str, Any]]) -> "Frames":
    """
    Add backend-agnostic validation constraints to frames.meta["constraints"].
    Expected rule format (per item):
      { sheet: str, column: str,
        rule: { type: "in_list", values: [...] },   # MVP supports in_list
        on_violation: "error" | "warn" | "coerce" } # default "error"
    """
    meta = dict(frames.meta or {})
    constraints = list(meta.get("constraints") or [])
    for r in rules:
        # minimal sanity: require fields
        if not isinstance(r, dict) or "sheet" not in r or "rule" not in r:
            raise ValueError(f"invalid validation rule: {r}")
        rule = r.get("rule") or {}
        if rule.get("type") != "in_list":
            raise ValueError(f"unsupported rule.type={rule.get('type')} (MVP supports 'in_list')")
        constraints.append({
            "sheet": r["sheet"],
            "column": r.get("column"),            # optional if you use explicit ranges later
            "rule": {"type": "in_list", "values": list(rule.get("values") or [])},
            "on_violation": r.get("on_violation", "error"),
        })
    meta["constraints"] = constraints
    frames.meta = meta
    return frames
