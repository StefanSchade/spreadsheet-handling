from __future__ import annotations

import pytest

from spreadsheet_handling.rendering.formulas import (
    ListLiteralFormulaSpec,
    formula_list_values,
    list_literal_formula,
)


pytestmark = pytest.mark.ftr("FTR-FORMULA-PROVIDERS")


def test_list_literal_formula_normalizes_values_to_strings() -> None:
    formula = list_literal_formula(["new", 2, None])

    assert formula == ListLiteralFormulaSpec(("new", "2", "None"))
    assert formula_list_values(formula) == ("new", "2", "None")
