from __future__ import annotations

from dataclasses import dataclass
import re

from ._base import NamedRange, WorkbookIR


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


__all__ = ["NamedRangePass"]
