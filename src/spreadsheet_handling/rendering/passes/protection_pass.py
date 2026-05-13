from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Dict

from ._base import (
    TableBlock,
    WorkbookIR,
    _derived_helper_column_names,
    _helper_column_names_from_value,
    _workbook_meta,
)


@dataclass
class ProtectionPass:
    """Resolve editable/locked column intent into protection metadata."""

    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        workbook_meta = _workbook_meta(doc)
        for sh in doc.sheets.values():
            opts: Dict[str, Any] = sh.meta.get("options", {})
            protection = opts.get("protection")
            if not protection:
                continue
            if not isinstance(protection, Mapping):
                raise TypeError(
                    f"Sheet {sh.name!r} options.protection must be a mapping"
                )
            if not sh.tables:
                continue
            t = sh.tables[0]

            editable_columns = _protection_editable_columns(
                protection, opts, workbook_meta, sheet_name=sh.name, frame_name=t.frame_name
            )
            locked_cols, unlocked_cols = _protection_column_indices(
                t, editable_columns=editable_columns
            )

            sh.meta["__protection"] = {
                "locked_cols": locked_cols,
                "unlocked_cols": unlocked_cols,
                "password": protection.get("password"),
            }

        return doc


def _protection_editable_columns(
    protection: Mapping[str, Any],
    opts: Mapping[str, Any],
    workbook_meta: Mapping[str, Any],
    *,
    sheet_name: str,
    frame_name: str,
) -> list[str]:
    explicit = protection.get("editable_columns")
    if explicit is not None:
        return _helper_column_names_from_value(explicit)

    editable = protection.get("editable")
    if editable == "non_helper":
        helper_names = _helper_column_names_from_value(opts.get("helper_columns"))
        helper_names.extend(
            _derived_helper_column_names(
                workbook_meta, sheet_name=sheet_name, frame_name=frame_name
            )
        )
        return ["*", *[f"!{name}" for name in helper_names]]

    return []


def _protection_column_indices(
    table: TableBlock,
    *,
    editable_columns: list[str],
) -> tuple[list[int], list[int]]:
    if not editable_columns:
        return [], []

    all_indices = sorted(table.header_map.values())
    if not all_indices:
        return [], []

    exclude_mode = any(name.startswith("*") for name in editable_columns)
    if exclude_mode:
        excluded = {
            name.lstrip("!") for name in editable_columns if name.startswith("!")
        }
        unlocked = [
            idx
            for name, idx in table.header_map.items()
            if str(name) not in excluded
        ]
        locked = [idx for idx in all_indices if idx not in set(unlocked)]
    else:
        editable_set = set(editable_columns)
        unlocked = [
            idx for name, idx in table.header_map.items() if str(name) in editable_set
        ]
        locked = [idx for idx in all_indices if idx not in set(unlocked)]

    return sorted(set(locked)), sorted(set(unlocked))


__all__ = ["ProtectionPass"]
