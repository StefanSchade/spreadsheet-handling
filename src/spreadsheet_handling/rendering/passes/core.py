from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Dict, Any, List, Optional
from ..ir import WorkbookIR, SheetIR, DataValidationSpec, NamedRange

class IRPass(Protocol):
    def apply(self, doc: WorkbookIR) -> WorkbookIR: ...

@dataclass
class StylePass:
    default_header_fill_rgb: str = "#F2F2F2"
    default_helper_fill_rgb: str | None = "#E8F0FE"
    helper_prefix: str = "_"

    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        for sh in doc.sheets.values():
            opts: Dict[str, Any] = sh.meta.get("options", {})

            # Header style
            header_fill = opts.get("header_fill_rgb", self.default_header_fill_rgb)
            style = {"header": {"bold": True, "fill": header_fill}}
            styles = sh.meta.get("__style", {})
            styles.update(style)
            sh.meta["__style"] = styles

            # Helper column highlighting
            helper_fill = opts.get("helper_fill_rgb", self.default_helper_fill_rgb)
            prefix = opts.get("helper_prefix", self.helper_prefix)
            if helper_fill and sh.tables:
                t = sh.tables[0]
                helper_cols = [
                    idx for name, idx in t.header_map.items()
                    if str(name).startswith(prefix)
                ]
                if helper_cols:
                    sh.meta["__helper_cols"] = {
                        "cols": helper_cols,
                        "fill": helper_fill,
                    }

        return doc

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
                formula = '"' + ",".join(values) + '"'
                dv = DataValidationSpec(kind="list", area=(r1, col, r2, col), formula=formula, allow_empty=True)
                sh.validations.append(dv)

        # New path: workbook-level constraints (column name based)
        meta_sheet: Optional[SheetIR] = doc.hidden_sheets.get("_meta")
        wb_meta = (meta_sheet.meta.get("workbook_meta_blob") or {}) if meta_sheet else {}
        constraints = wb_meta.get("constraints") or [] if isinstance(wb_meta, dict) else []
        for c in constraints:
            if not isinstance(c, dict):
                continue
            sheet_name = c.get("sheet")
            col_name = c.get("column")
            rule = c.get("rule") or {}
            if not sheet_name or not col_name:
                continue
            if rule.get("type") != "in_list":
                continue
            target = doc.sheets.get(str(sheet_name))
            if not target or not target.tables:
                continue
            t = target.tables[0]
            col_idx = t.header_map.get(str(col_name))
            if not col_idx:
                continue
            r1 = t.top + t.header_rows
            r2 = max(r1, t.top + t.n_rows - 1)
            values = [str(v) for v in (rule.get("values") or [])]
            formula = '"' + ",".join(values) + '"'
            dv = DataValidationSpec(kind="list", area=(r1, col_idx, r2, col_idx), formula=formula, allow_empty=True)
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
        for f in (self.minimal_fields or []):
            meta.meta.setdefault(f, "")
        meta.meta["_hidden"] = True
        return doc


import re

def _safe_name(s: str) -> str:
    """Sanitise a string for use in the current spreadsheet-safe defined-name subset."""
    return re.sub(r'[^A-Za-z0-9_]', '_', s).strip('_').lower() or "unnamed"


@dataclass
class NamedRangePass:
    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        for sh in doc.sheets.values():
            for tbl in sh.tables:
                prefix = _safe_name(sh.name) + "_" + _safe_name(tbl.frame_name)

                # Full table (headers + data)
                sh.named_ranges.append(NamedRange(
                    name=f"{prefix}_table",
                    sheet=sh.name,
                    area=(tbl.top, tbl.left,
                          tbl.top + tbl.n_rows - 1, tbl.left + tbl.n_cols - 1),
                ))

                # Header area
                if tbl.header_rows >= 1:
                    sh.named_ranges.append(NamedRange(
                        name=f"{prefix}_header",
                        sheet=sh.name,
                        area=(tbl.top, tbl.left,
                              tbl.top + tbl.header_rows - 1, tbl.left + tbl.n_cols - 1),
                    ))

                # Data body (below headers)
                data_top = tbl.top + tbl.header_rows
                data_bot = tbl.top + tbl.n_rows - 1
                if data_bot >= data_top:
                    sh.named_ranges.append(NamedRange(
                        name=f"{prefix}_body",
                        sheet=sh.name,
                        area=(data_top, tbl.left,
                              data_bot, tbl.left + tbl.n_cols - 1),
                    ))
        return doc
