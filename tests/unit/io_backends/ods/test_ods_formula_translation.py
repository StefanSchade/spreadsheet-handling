from __future__ import annotations

import pytest

from spreadsheet_handling.io_backends.ods.odf_parser import _parse_validation_formula
from spreadsheet_handling.io_backends.ods.odf_renderer import _ods_validation_condition
from spreadsheet_handling.rendering.formulas import ListLiteralFormulaSpec


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
