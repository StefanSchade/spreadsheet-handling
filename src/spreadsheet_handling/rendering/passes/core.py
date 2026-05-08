from __future__ import annotations
from collections.abc import Mapping
import logging
import re
from dataclasses import dataclass
from typing import Protocol, Dict, Any, List, Optional
from ..formulas import list_literal_formula
from ..ir import WorkbookIR, SheetIR, TableBlock, DataValidationSpec, NamedRange

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


@dataclass
class StylePass:
    default_header_fill_rgb: str = "#F2F2F2"
    default_legend_header_fill_rgb: str = "#D9EAD3"
    default_helper_fill_rgb: str | None = "#E8F0FE"
    helper_prefix: str = "_"

    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        workbook_meta = _workbook_meta(doc)
        for sh in doc.sheets.values():
            opts: Dict[str, Any] = sh.meta.get("options", {})

            # Header style
            header_fill = opts.get("header_fill_rgb", self.default_header_fill_rgb)
            legend_header_fill = opts.get(
                "legend_header_fill_rgb",
                self.default_legend_header_fill_rgb,
            )
            style = {
                "header": {"bold": True, "fill": header_fill},
                "legend_header": {"bold": True, "fill": legend_header_fill},
            }
            styles = sh.meta.get("__style", {})
            styles.update(style)
            sh.meta["__style"] = styles

            # Helper column highlighting
            helper_fill = opts.get("helper_fill_rgb", self.default_helper_fill_rgb)
            prefix = opts.get("helper_prefix", self.helper_prefix)
            if helper_fill and sh.tables:
                t = sh.tables[0]
                explicit_columns = _helper_column_names_from_value(opts.get("helper_columns"))
                explicit_columns.extend(
                    _derived_helper_column_names(
                        workbook_meta,
                        sheet_name=sh.name,
                        frame_name=t.frame_name,
                    )
                )
                helper_cols = _helper_column_indices(
                    t,
                    explicit_columns=list(dict.fromkeys(explicit_columns)),
                    helper_prefix=prefix,
                )
                if helper_cols:
                    sh.meta["__helper_cols"] = {
                        "cols": helper_cols,
                        "fill": helper_fill,
                    }

        return doc


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


@dataclass
class FilterPass:
    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        for sh in doc.sheets.values():
            opts: Dict[str, Any] = sh.meta.get("options", {})
            if not opts.get("auto_filter", True):
                continue
            if not sh.tables:
                continue
            t = sh.tables[0]
            if t.n_cols == 0 or t.n_rows == 0:
                continue
            sh.meta["__autofilter"] = {
                "top_left": (t.top, t.left),
                "bottom_right": (t.top + t.n_rows - 1, t.left + t.n_cols - 1),
            }
        return doc


@dataclass
class FreezePass:
    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        for sh in doc.sheets.values():
            opts: Dict[str, Any] = sh.meta.get("options", {})
            if opts.get("freeze_header", False):
                if sh.tables:
                    t = sh.tables[0]
                    sh.meta["__freeze"] = {"row": t.top + t.header_rows, "col": t.left}
                else:
                    sh.meta["__freeze"] = {"row": 2, "col": 1}
        return doc


@dataclass
class ColumnWidthPass:
    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        for sh in doc.sheets.values():
            opts: Dict[str, Any] = sh.meta.get("options", {})
            widths = opts.get("column_widths") or opts.get("__column_widths")
            if widths:
                sh.meta["__column_widths"] = widths
        return doc


def _workbook_meta(doc: WorkbookIR) -> dict[str, Any]:
    meta_sheet: Optional[SheetIR] = doc.hidden_sheets.get("_meta")
    if not meta_sheet:
        return {}
    wb_meta = meta_sheet.meta.get("workbook_meta_blob") or {}
    return wb_meta if isinstance(wb_meta, dict) else {}


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


@dataclass
class MetaPass:
    minimal_fields: Optional[List[str]] = None

    def __post_init__(self):
        if self.minimal_fields is None:
            self.minimal_fields = ["version", "exported_at", "author"]

    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        meta: SheetIR = doc.hidden_sheets.get("_meta") or SheetIR(name="_meta", meta={})
        if "_meta" not in doc.hidden_sheets:
            doc.hidden_sheets["_meta"] = meta
        for f in self.minimal_fields or []:
            meta.meta.setdefault(f, "")
        meta.meta["_hidden"] = True
        return doc


def _safe_name(s: str) -> str:
    """Sanitise a string for use in the current spreadsheet-safe defined-name subset."""
    return re.sub(r"[^A-Za-z0-9_]", "_", s).strip("_").lower() or "unnamed"


@dataclass
class NamedRangePass:
    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        for sh in doc.sheets.values():
            for tbl in sh.tables:
                prefix = _safe_name(sh.name) + "_" + _safe_name(tbl.frame_name)

                # Full table (headers + data)
                sh.named_ranges.append(
                    NamedRange(
                        name=f"{prefix}_table",
                        sheet=sh.name,
                        area=(
                            tbl.top,
                            tbl.left,
                            tbl.top + tbl.n_rows - 1,
                            tbl.left + tbl.n_cols - 1,
                        ),
                    )
                )

                # Header area
                if tbl.header_rows >= 1:
                    sh.named_ranges.append(
                        NamedRange(
                            name=f"{prefix}_header",
                            sheet=sh.name,
                            area=(
                                tbl.top,
                                tbl.left,
                                tbl.top + tbl.header_rows - 1,
                                tbl.left + tbl.n_cols - 1,
                            ),
                        )
                    )

                # Data body (below headers)
                data_top = tbl.top + tbl.header_rows
                data_bot = tbl.top + tbl.n_rows - 1
                if data_bot >= data_top:
                    sh.named_ranges.append(
                        NamedRange(
                            name=f"{prefix}_body",
                            sheet=sh.name,
                            area=(data_top, tbl.left, data_bot, tbl.left + tbl.n_cols - 1),
                        )
                    )
        return doc
