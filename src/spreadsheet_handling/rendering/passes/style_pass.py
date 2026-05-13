from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from ._base import (
    WorkbookIR,
    _derived_helper_column_names,
    _helper_column_indices,
    _helper_column_names_from_value,
    _workbook_meta,
)


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


__all__ = ["StylePass"]
