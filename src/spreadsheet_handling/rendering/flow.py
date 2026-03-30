from __future__ import annotations
from typing import List, Dict, Any
from .ir import WorkbookIR, SheetIR, TableBlock
from .passes.core import IRPass, StylePass, FilterPass, FreezePass, ValidationPass, MetaPass
from .plan import (
    RenderPlan,
    DefineSheet,
    SetHeader,
    MergeCells,
    ApplyHeaderStyle,
    ApplyColumnStyle,
    SetAutoFilter,
    SetFreeze,
    AddValidation,
    WriteMeta,
)

def compose_ir(domain_input: Dict[str, Any]) -> WorkbookIR:
    """
    Compose a minimal IR from a simple DTO (temporary for P1).
    """
    wb = WorkbookIR()
    for sheet_dto in domain_input.get("sheets", []):
        name = sheet_dto["name"]
        headers = sheet_dto.get("headers", [])
        rows = sheet_dto.get("rows", [])
        n_rows = len(rows) + 1 if headers else len(rows)
        n_cols = len(headers) if headers else (len(rows[0]) if rows else 0)
        header_map = {h: idx + 1 for idx, h in enumerate(headers)}

        table = TableBlock(
            frame_name="main",
            top=1,
            left=1,
            header_rows=1 if headers else 0,
            header_cols=1,
            n_rows=n_rows,
            n_cols=n_cols,
            headers=headers,
            header_map=header_map,
        )
        sheet_ir = SheetIR(name=name, tables=[table], meta=sheet_dto.get("meta", {}))

        # carry validation DTOs (for ValidationPass)
        p1_valids = sheet_dto.get("validations", [])
        if p1_valids:
            sheet_ir.meta["_p1_validations"] = p1_valids

        # options (style/autofilter/freeze)
        opts = sheet_dto.get("options", {})
        if opts:
            sheet_ir.meta["options"] = opts

        wb.sheets[name] = sheet_ir

    # workbook-level meta on hidden _meta sheet
    hidden_meta_sheet = SheetIR(name="_meta", meta=domain_input.get("workbook_meta", {}))
    wb.hidden_sheets["_meta"] = hidden_meta_sheet

    return wb

def apply_ir_passes(doc: WorkbookIR, passes: List[IRPass]) -> WorkbookIR:
    for p in passes:
        doc = p.apply(doc)
    return doc

def build_render_plan(doc: WorkbookIR) -> RenderPlan:
    """
    Convert the IR document into a backend-agnostic RenderPlan (sequence of RenderOps).
    """
    plan = RenderPlan()

    for sheet_name, sh in doc.sheets.items():
        plan.add(DefineSheet(sheet=sheet_name, order=len(plan.sheet_order)))

        if sh.tables:
            t = sh.tables[0]
            header_grid = sh.meta.get("__header_grid")
            if header_grid and t.header_rows >= 1:
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
            header_style = styles.get("header")
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

        af = sh.meta.get("__autofilter")
        if af:
            (r1, c1) = af["top_left"]
            (r2, c2) = af["bottom_right"]
            plan.add(SetAutoFilter(sheet=sheet_name, r1=r1, c1=c1, r2=r2, c2=c2))

        fz = sh.meta.get("__freeze")
        if fz:
            plan.add(SetFreeze(sheet=sheet_name, row=int(fz["row"]), col=int(fz["col"])))

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

    for sheet_name, sh in doc.hidden_sheets.items():
        hidden = bool(sh.meta.get("_hidden", True))
        kv = {k: v for k, v in sh.meta.items() if k != "_hidden"}
        plan.add(WriteMeta(sheet=sheet_name, kv={str(k): str(v) for k, v in kv.items()}, hidden=hidden))

    return plan

def default_p1_passes() -> List[IRPass]:
    return [MetaPass(), ValidationPass(), StylePass(), FilterPass(), FreezePass()]
