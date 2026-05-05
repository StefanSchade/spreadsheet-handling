from __future__ import annotations

from typing import Any, Dict

import pandas as pd

Frames = Dict[str, pd.DataFrame]


def add_validations(frames: Frames, *, rules: list[dict[str, Any]]) -> Frames:
    # get or create meta on either frames.meta (attr) or frames["_meta"] (dict key)
    if hasattr(frames, "meta"):
        meta = frames.meta or {}
        where = "attr"
    elif isinstance(frames, dict):
        meta = frames.get("_meta") or {}
        frames["_meta"] = meta
        where = "key"
    else:
        # last resort: create a temporary sidecar
        meta = {}
        where = "temp"

    constraints = list(meta.get("constraints") or [])
    for r in rules:
        rule = (r.get("rule") or {})
        rule_type = rule.get("type")
        if rule_type == "in_list":
            constraint_rule = {
                "type": "in_list",
                "values": list(rule.get("values") or []),
            }
        elif rule_type == "from_legend":
            constraint_rule = {
                "type": "from_legend",
                "legend": rule.get("legend"),
            }
            if "include_empty" in rule:
                constraint_rule["include_empty"] = bool(rule.get("include_empty"))
        else:
            raise ValueError(f"unsupported rule.type={rule.get('type')}")
        constraint = {
            "sheet": r["sheet"],
            "column": r.get("column"),
            "rule": constraint_rule,
            "on_violation": r.get("on_violation", "error"),
        }
        if r.get("area") is not None:
            constraint["area"] = r.get("area")
        constraints.append(constraint)

    meta["constraints"] = constraints

    if where == "attr":
        frames.meta = meta
    elif where == "key":
        frames["_meta"] = meta

    return frames
