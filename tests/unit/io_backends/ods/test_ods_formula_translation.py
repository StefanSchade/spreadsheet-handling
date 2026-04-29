from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from spreadsheet_handling.io_backends.ods.odf_parser import _parse_validation_formula
from spreadsheet_handling.io_backends.ods.odf_renderer import (
    _ods_lookup_formula,
    _ods_validation_condition,
    render_workbook,
)
from spreadsheet_handling.rendering.formulas import ListLiteralFormulaSpec, lookup_formula
from spreadsheet_handling.rendering.plan import DefineSheet, RenderPlan, SetHeader, WriteDataBlock


pytestmark = pytest.mark.ftr("FTR-FORMULA-PROVIDERS")


def test_ods_translates_list_literal_formula_spec() -> None:
    formula = ListLiteralFormulaSpec(("new", "done"))

    assert _ods_validation_condition(formula) == (
        'of:cell-content-is-in-list("new";"done")'
    )


def test_ods_parser_recovers_list_literal_formula_spec() -> None:
    assert _parse_validation_formula('of:cell-content-is-in-list("new";"done")') == (
        ListLiteralFormulaSpec(("new", "done"))
    )


def test_ods_translator_and_parser_preserve_commas_and_quotes() -> None:
    formula = ListLiteralFormulaSpec(("needs,review", 'he said "yes"'))

    rendered = _ods_validation_condition(formula)

    assert rendered == 'of:cell-content-is-in-list("needs,review";"he said ""yes""")'
    assert _parse_validation_formula(rendered) == formula


@pytest.mark.ftr("FTR-FORMULA-FK-HELPER-PROVIDERS-P4A")
def test_ods_translates_lookup_formula_spec() -> None:
    formula = lookup_formula(
        source_key_column="id_(Customers)",
        lookup_sheet="Customers",
        lookup_key_column="id",
        lookup_value_column="name",
    )

    rendered = _ods_lookup_formula(
        formula,
        current_sheet="Orders",
        row=5,
        sheet_headers={
            "Orders": {"id": 1, "id_(Customers)": 2, "_Customers_name": 3},
            "Customers": {"id": 1, "name": 2},
        },
        sheet_data_bounds={"Orders": (2, 5), "Customers": (2, 4)},
    )

    assert rendered == (
        'of:=XLOOKUP([.B5];[Customers.A2:Customers.A4];[Customers.B2:Customers.B4];"")'
    )


@pytest.mark.ftr("FTR-FORMULA-FK-HELPER-PROVIDERS-P4A")
def test_ods_renderer_emits_lookup_formula_cells(tmp_path: Path) -> None:
    formula = lookup_formula(
        source_key_column="id_(Customers)",
        lookup_sheet="Customers",
        lookup_key_column="id",
        lookup_value_column="name",
    )
    plan = RenderPlan()
    plan.add(DefineSheet("Orders", 0))
    plan.add(SetHeader("Orders", 1, 1, "id"))
    plan.add(SetHeader("Orders", 1, 2, "id_(Customers)"))
    plan.add(SetHeader("Orders", 1, 3, "_Customers_name"))
    plan.add(WriteDataBlock("Orders", 2, 1, (("O-1", "C-1", formula),)))
    plan.add(DefineSheet("Customers", 1))
    plan.add(SetHeader("Customers", 1, 1, "id"))
    plan.add(SetHeader("Customers", 1, 2, "name"))
    plan.add(WriteDataBlock("Customers", 2, 1, (("C-1", "Ada"), ("C-2", "Bob"))))

    out = tmp_path / "lookup_formula.ods"
    render_workbook(plan, out)

    with ZipFile(out) as archive:
        content = archive.read("content.xml").decode("utf-8")

    assert "table:formula='of:=XLOOKUP" in content
    assert "Customers.A2:Customers.A3" in content
    assert "Customers.B2:Customers.B3" in content
