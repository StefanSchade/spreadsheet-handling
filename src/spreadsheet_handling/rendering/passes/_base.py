from __future__ import annotations

import ast
from collections.abc import Mapping
import json
import logging
from typing import Any, Protocol

from ..ir import DataValidationSpec, NamedRange, SheetIR, TableBlock, WorkbookIR

log = logging.getLogger("sheets.validation")
_LEGEND_DROPDOWN_WARNING_THRESHOLD = 50


class IRPass(Protocol):
    def apply(self, doc: WorkbookIR) -> WorkbookIR: ...


def _helper_column_names_from_value(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, Mapping):
        if "columns" in raw:
            return _helper_column_names_from_value(raw.get("columns"))
        if "column" in raw:
            return _helper_column_names_from_value(raw.get("column"))
        return []

    try:
        values = list(raw)
    except TypeError:
        return []

    names: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            value = value.get("column") or value.get("name")
        if value is None:
            continue
        text = str(value)
        if text.strip():
            names.append(text)
    return list(dict.fromkeys(names))


def _sheet_source_candidates(
    workbook_meta: Mapping[str, Any],
    *,
    sheet_name: str,
    frame_name: str,
) -> list[str]:
    candidates = [sheet_name, frame_name]
    view = workbook_meta.get("workbook_view")
    if isinstance(view, Mapping):
        sheets = view.get("sheets")
        if isinstance(sheets, list):
            for entry in sheets:
                if not isinstance(entry, Mapping):
                    continue
                rendered_sheet = str(entry.get("sheet") or entry.get("frame") or "")
                source_frame = entry.get("frame")
                if rendered_sheet == sheet_name and source_frame is not None:
                    candidates.append(str(source_frame))
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def _derived_helper_column_names(
    workbook_meta: Mapping[str, Any],
    *,
    sheet_name: str,
    frame_name: str,
) -> list[str]:
    derived = workbook_meta.get("derived")
    if not isinstance(derived, Mapping):
        return []
    derived_sheets = derived.get("sheets")
    if not isinstance(derived_sheets, Mapping):
        return []

    names: list[str] = []
    for candidate in _sheet_source_candidates(
        workbook_meta,
        sheet_name=sheet_name,
        frame_name=frame_name,
    ):
        sheet_meta = derived_sheets.get(candidate)
        if not isinstance(sheet_meta, Mapping):
            continue
        names.extend(_helper_column_names_from_value(sheet_meta.get("helper_columns")))
        enrich_lookup = sheet_meta.get("enrich_lookup")
        if isinstance(enrich_lookup, Mapping):
            names.extend(_helper_column_names_from_value(enrich_lookup.get("helper_columns")))
    return list(dict.fromkeys(names))


def _helper_column_indices(
    table: TableBlock,
    *,
    explicit_columns: list[str],
    helper_prefix: Any,
) -> list[int]:
    explicit = set(explicit_columns)
    prefix = "" if helper_prefix is None else str(helper_prefix)
    indices: list[int] = []
    for name, idx in table.header_map.items():
        text = str(name)
        if text in explicit or (prefix and text.startswith(prefix)):
            indices.append(idx)
    return sorted(set(indices))


def _workbook_meta(doc: WorkbookIR) -> dict[str, Any]:
    meta_sheet: SheetIR | None = doc.hidden_sheets.get("_meta")
    if not meta_sheet:
        return {}
    wb_meta = meta_sheet.meta.get("workbook_meta_blob") or {}
    if isinstance(wb_meta, dict):
        return wb_meta
    if isinstance(wb_meta, str):
        try:
            parsed = json.loads(wb_meta)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            # legacy: pre-JSON repr format
            parsed = ast.literal_eval(wb_meta)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, SyntaxError, TypeError):
            pass
    return {}


def _legend_spec(wb_meta: dict[str, Any], legend_name: str) -> dict[str, Any] | None:
    raw = wb_meta.get("legend_blocks")
    if isinstance(raw, dict):
        spec = raw.get(legend_name)
        return spec if isinstance(spec, dict) else None
    if isinstance(raw, list):
        for index, spec in enumerate(raw, start=1):
            if not isinstance(spec, dict):
                continue
            name = str(spec.get("name") or spec.get("id") or f"legend_{index}")
            if name == legend_name:
                return spec
    return None


def _legend_tokens(
    wb_meta: dict[str, Any],
    *,
    legend_name: str,
    include_empty: bool,
) -> list[str] | None:
    spec = _legend_spec(wb_meta, legend_name)
    if spec is None:
        log.warning("from_legend validation references unknown legend block %r", legend_name)
        return None

    entries = spec.get("entries")
    if not isinstance(entries, list):
        log.warning(
            "from_legend validation references legend block %r without entries", legend_name
        )
        return None

    tokens = [
        str(entry["token"])
        for entry in entries
        if isinstance(entry, dict) and entry.get("token") not in (None, "")
    ]
    if len(tokens) > _LEGEND_DROPDOWN_WARNING_THRESHOLD:
        log.warning(
            "from_legend validation for legend block %r has %d values; Excel dropdown UX may degrade",
            legend_name,
            len(tokens),
        )
    if include_empty:
        return ["", *tokens]
    return tokens


def _validation_values(rule: dict[str, Any], wb_meta: dict[str, Any]) -> list[str] | None:
    rule_type = rule.get("type")
    if rule_type == "in_list":
        return [str(v) for v in (rule.get("values") or [])]
    if rule_type == "from_legend":
        legend_name = rule.get("legend")
        if not legend_name:
            return None
        return _legend_tokens(
            wb_meta,
            legend_name=str(legend_name),
            include_empty=bool(rule.get("include_empty", False)),
        )
    return None


def _target_validation_columns(
    table: TableBlock,
    *,
    column_name: Any,
    area: Any,
) -> list[int]:
    if column_name == "*" or (not column_name and area == "data_body"):
        return sorted(table.header_map.values())
    col_idx = table.header_map.get(str(column_name))
    return [col_idx] if col_idx else []


__all__ = [
    "DataValidationSpec",
    "IRPass",
    "NamedRange",
    "SheetIR",
    "TableBlock",
    "WorkbookIR",
]
