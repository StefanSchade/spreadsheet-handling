from __future__ import annotations
import ast
import json
from typing import List, Any
from .ir import WorkbookIR, SheetIR, TableBlock
from .passes import (
    default_passes,
    IRPass,
)
from .plan import (
    RenderPlan,
    DefineSheet,
    SetHeader,
    MergeCells,
    ApplyHeaderStyle,
    ApplyColumnStyle,
    SetAutoFilter,
    SetFreeze,
    SetColumnWidth,
    SetHorizontalAlignment,
    SetTextOrientation,
    AddValidation,
    WriteDataBlock,
    WriteMeta,
    DefineNamedRange,
    SetSheetProtection,
    ApplyCellLock,
)


_CANONICAL_HORIZONTAL_ALIGNMENTS: frozenset[str] = frozenset({"left", "center", "right"})

def apply_ir_passes(doc: WorkbookIR, passes: List[IRPass]) -> WorkbookIR:
    for p in passes:
        doc = p.apply(doc)
    return doc


def _dump_workbook_meta_blob(value: Any) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            try:
                # legacy: normalize pre-JSON repr blobs when re-rendering parsed IR.
                parsed = ast.literal_eval(value)
            except (ValueError, SyntaxError, TypeError):
                parsed = value
        if isinstance(parsed, dict):
            value = parsed
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _meta_cell_value(key: str, value: Any) -> str:
    if key == "workbook_meta_blob":
        return _dump_workbook_meta_blob(value)
    return str(value)


def _header_grid_for_table(sh: SheetIR, table: TableBlock, table_index: int) -> Any:
    if table_index != 0:
        return None
    header_grid = sh.meta.get("__header_grid")
    if header_grid and table.header_rows >= 1:
        return header_grid
    return None


def _sheet_column_extent(sh: SheetIR) -> int:
    return max(
        (table.left + table.n_cols - 1 for table in sh.tables if table.n_cols > 0),
        default=0,
    )


def _column_key_to_index(key: Any) -> int | None:
    if isinstance(key, int):
        return key if key > 0 else None

    text = str(key).strip()
    if not text:
        return None
    if text.isdigit():
        idx = int(text)
        return idx if idx > 0 else None
    if not text.isalpha():
        return None

    idx = 0
    for char in text.upper():
        idx = idx * 26 + (ord(char) - ord("A") + 1)
    return idx if idx > 0 else None


def _column_width_value(spec: Any) -> float | None:
    raw = spec.get("width") if isinstance(spec, dict) else spec
    try:
        width = float(raw)
    except (TypeError, ValueError):
        return None
    return width if width > 0 else None


def _column_width_ops(sheet_name: str, sh: SheetIR) -> list[SetColumnWidth]:
    raw = sh.meta.get("__column_widths")
    if not isinstance(raw, dict):
        return []

    max_col = _sheet_column_extent(sh)
    ops: list[SetColumnWidth] = []
    for key, spec in raw.items():
        col = _column_key_to_index(key)
        width = _column_width_value(spec)
        if col is None or width is None:
            continue
        if max_col and col > max_col:
            continue
        ops.append(SetColumnWidth(sheet=sheet_name, col=col, width=width))
    return sorted(ops, key=lambda op: op.col)


def _cell_address_to_row_col(address: Any) -> tuple[int, int] | None:
    """Parse a cell address like "B1" or (row, col) into a (row, col) 1-based int pair."""
    if isinstance(address, (list, tuple)) and len(address) == 2:
        try:
            return int(address[0]), int(address[1])
        except (TypeError, ValueError):
            return None
    text = str(address).strip().upper()
    import re
    m = re.fullmatch(r"([A-Z]+)(\d+)", text)
    if not m:
        return None
    col = _column_key_to_index(m.group(1))
    row = int(m.group(2))
    if col is None or row < 1:
        return None
    return row, col


def _text_orientation_ops(sheet_name: str, sh: SheetIR) -> list[SetTextOrientation]:
    raw = sh.meta.get("__text_orientations")
    if not isinstance(raw, dict):
        return []
    ops: list[SetTextOrientation] = []
    for address, spec in raw.items():
        rc = _cell_address_to_row_col(address)
        if rc is None:
            continue
        row, col = rc
        rotation = spec.get("rotation") if isinstance(spec, dict) else spec
        try:
            rotation = int(rotation)
        except (TypeError, ValueError):
            continue
        if rotation < 0 or rotation > 180:
            continue
        ops.append(SetTextOrientation(sheet=sheet_name, row=row, col=col, rotation=rotation))
    return sorted(ops, key=lambda op: (op.row, op.col))


def _horizontal_alignment_ops(sheet_name: str, sh: SheetIR) -> list[SetHorizontalAlignment]:
    raw = sh.meta.get("__horizontal_alignments")
    if not isinstance(raw, dict):
        return []
    ops: list[SetHorizontalAlignment] = []
    for address, spec in raw.items():
        rc = _cell_address_to_row_col(address)
        if rc is None:
            continue
        row, col = rc
        value = spec.get("horizontal") if isinstance(spec, dict) else spec
        if not isinstance(value, str):
            continue
        canonical = value.strip().lower()
        if canonical not in _CANONICAL_HORIZONTAL_ALIGNMENTS:
            continue
        ops.append(
            SetHorizontalAlignment(
                sheet=sheet_name, row=row, col=col, horizontal=canonical
            )
        )
    return sorted(ops, key=lambda op: (op.row, op.col))


def build_render_plan(doc: WorkbookIR) -> RenderPlan:
    """
    Convert the IR document into a backend-agnostic RenderPlan (sequence of RenderOps).
    """
    plan = RenderPlan()

    for sheet_name, sh in doc.sheets.items():
        plan.add(DefineSheet(sheet=sheet_name, order=len(plan.sheet_order)))

        for table_index, t in enumerate(sh.tables):
            header_grid = _header_grid_for_table(sh, t, table_index)
            if header_grid:
                for row_off, row_vals in enumerate(header_grid):
                    r = t.top + row_off
                    for idx, text in enumerate(row_vals, start=0):
                        c = t.left + idx
                        if text:
                            plan.add(SetHeader(sheet=sheet_name, row=r, col=c, text=text))
                for m in sh.meta.get("__header_merges", []) or []:
                    mr1, mc1, mr2, mc2 = map(int, m)
                    plan.add(MergeCells(
                        sheet=sheet_name,
                        r1=t.top + mr1 - 1,
                        c1=t.left + mc1 - 1,
                        r2=t.top + mr2 - 1,
                        c2=t.left + mc2 - 1,
                    ))
            elif t.headers and t.header_rows >= 1:
                r = t.top
                for idx, text in enumerate(t.headers, start=0):
                    c = t.left + idx
                    plan.add(SetHeader(sheet=sheet_name, row=r, col=c, text=text))
            styles = sh.meta.get("__style", {})
            header_style = styles.get("legend_header") if t.kind == "legend" else styles.get("header")
            if header_style and t.n_cols:
                for r in range(t.top, t.top + max(1, t.header_rows)):
                    for idx in range(t.n_cols):
                        c = t.left + idx
                        plan.add(ApplyHeaderStyle(
                            sheet=sheet_name,
                            row=r,
                            col=c,
                            bold=bool(header_style.get("bold", False)),
                            fill_rgb=header_style.get("fill"),
                        ))

            # Data cells
            if t.data is not None:
                data_start = t.top + t.header_rows
                plan.add(WriteDataBlock(
                    sheet=sheet_name,
                    r1=data_start,
                    c1=t.left,
                    data=tuple(tuple(row) for row in t.data),
                ))

        af = sh.meta.get("__autofilter")
        if af:
            (r1, c1) = af["top_left"]
            (r2, c2) = af["bottom_right"]
            plan.add(SetAutoFilter(sheet=sheet_name, r1=r1, c1=c1, r2=r2, c2=c2))

        fz = sh.meta.get("__freeze")
        if fz:
            plan.add(SetFreeze(sheet=sheet_name, row=int(fz["row"]), col=int(fz["col"])))

        for op in _column_width_ops(sheet_name, sh):
            plan.add(op)

        for op in _text_orientation_ops(sheet_name, sh):
            plan.add(op)

        for op in _horizontal_alignment_ops(sheet_name, sh):
            plan.add(op)

        # Helper column highlighting
        hc = sh.meta.get("__helper_cols")
        if hc and sh.tables:
            t = sh.tables[0]
            data_start = t.top + t.header_rows
            data_end = t.top + t.n_rows - 1
            if data_end >= data_start:
                for col_idx in hc["cols"]:
                    plan.add(ApplyColumnStyle(
                        sheet=sheet_name,
                        col=col_idx,
                        from_row=data_start,
                        to_row=data_end,
                        fill_rgb=hc["fill"],
                    ))
        for dv in sh.validations:
            plan.add(AddValidation(
                sheet=sheet_name,
                kind=dv.kind,
                r1=dv.area[0], c1=dv.area[1], r2=dv.area[2], c2=dv.area[3],
                formula=dv.formula,
                allow_empty=bool(dv.allow_empty),
            ))

        # Named ranges
        for nr in sh.named_ranges:
            plan.add(DefineNamedRange(
                name=nr.name,
                sheet=sheet_name,
                r1=nr.area[0], c1=nr.area[1], r2=nr.area[2], c2=nr.area[3],
            ))

        # Sheet protection
        prot = sh.meta.get("__protection")
        if prot and sh.tables:
            t = sh.tables[0]
            data_start = t.top + t.header_rows
            data_end = t.top + t.n_rows - 1
            all_start = t.top  # include headers
            if data_end >= data_start:
                for col_idx in prot["unlocked_cols"]:
                    plan.add(ApplyCellLock(
                        sheet=sheet_name,
                        col=col_idx,
                        from_row=all_start,
                        to_row=data_end,
                        locked=False,
                    ))
                plan.add(SetSheetProtection(
                    sheet=sheet_name,
                    password=prot.get("password"),
                ))

    for sheet_name, sh in doc.hidden_sheets.items():
        hidden = bool(sh.meta.get("_hidden", True))
        kv = {k: v for k, v in sh.meta.items() if k != "_hidden"}
        plan.add(
            WriteMeta(
                sheet=sheet_name,
                kv={str(k): _meta_cell_value(str(k), v) for k, v in kv.items()},
                hidden=hidden,
            )
        )

    return plan

def default_p1_passes() -> List[IRPass]:
    return default_passes()
