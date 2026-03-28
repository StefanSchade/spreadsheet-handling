from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Dict, Any, List
from ..ir import WorkbookIR, SheetIR, DataValidationSpec

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
        meta_sheet = doc.hidden_sheets.get("_meta")
        wb_meta = (meta_sheet.meta.get("workbook_meta_blob") or {}) if meta_sheet else {}
        constraints = wb_meta.get("constraints") or []
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
            sh = doc.sheets.get(str(sheet_name))
            if not sh or not sh.tables:
                continue
            t = sh.tables[0]
            col_idx = t.header_map.get(str(col_name))
            if not col_idx:
                continue
            r1 = t.top + t.header_rows
            r2 = max(r1, t.top + t.n_rows - 1)
            values = [str(v) for v in (rule.get("values") or [])]
            formula = '"' + ",".join(values) + '"'
            dv = DataValidationSpec(kind="list", area=(r1, col_idx, r2, col_idx), formula=formula, allow_empty=True)
            sh.validations.append(dv)

        return doc

@dataclass
class MetaPass:
    minimal_fields: List[str] = None
    def __post_init__(self):
        if self.minimal_fields is None:
            self.minimal_fields = ["version", "exported_at", "author"]
    def apply(self, doc: WorkbookIR) -> WorkbookIR:
        meta = doc.hidden_sheets.get("_meta")
        if not meta:
            meta = SheetIR(name="_meta", meta={})
            doc.hidden_sheets["_meta"] = meta
        for f in self.minimal_fields:
            meta.meta.setdefault(f, "")
        meta.meta["_hidden"] = True
        return doc
