# core/refs.py
from __future__ import annotations

from typing import Any, Callable


def add_helper_columns(records: list[dict[str, Any]], ref_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    ref_specs: z.B. [{"path_id": "char.id", "helper_path": "_char.name", "resolver": callable}]
    resolver(id) -> name
    """
    for r in records:
        for spec in ref_specs:
            pid = spec["path_id"]
            hp = spec["helper_path"]
            res = spec["resolver"]
            if pid in r:
                try:
                    r[hp] = res(r[pid])
                except Exception:
                    r[hp] = ""
    return records

