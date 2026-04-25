from __future__ import annotations

import pytest

from spreadsheet_handling.io_backends.xlsx.openpyxl_parser import _parse_xlsx_list_literal_formula
from spreadsheet_handling.io_backends.xlsx.openpyxl_renderer import _xlsx_validation_formula
from spreadsheet_handling.rendering.formulas import ListLiteralFormulaSpec


pytestmark = pytest.mark.ftr("FTR-FORMULA-PROVIDERS")


def test_xlsx_translates_list_literal_formula_spec() -> None:
    formula = ListLiteralFormulaSpec(("new", "done"))

    assert _xlsx_validation_formula(formula) == '"new,done"'


def test_xlsx_parser_recovers_list_literal_formula_spec() -> None:
    assert _parse_xlsx_list_literal_formula('"new,done"') == ListLiteralFormulaSpec(
        ("new", "done")
    )


def test_xlsx_translator_and_parser_preserve_commas_and_quotes() -> None:
    formula = ListLiteralFormulaSpec(("needs,review", 'he said "yes"'))

    rendered = _xlsx_validation_formula(formula)

    assert _parse_xlsx_list_literal_formula(rendered) == formula
