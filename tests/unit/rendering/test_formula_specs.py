from __future__ import annotations

import pytest

from spreadsheet_handling.rendering.formulas import (
    ListLiteralFormulaSpec,
    LookupFormulaSpec,
    formula_list_values,
    list_literal_formula,
    lookup_formula,
)


pytestmark = pytest.mark.ftr("FTR-FORMULA-PROVIDERS")


def test_list_literal_formula_normalizes_values_to_strings() -> None:
    formula = list_literal_formula(["new", 2, None])

    assert formula == ListLiteralFormulaSpec(("new", "2", "None"))
    assert formula_list_values(formula) == ("new", "2", "None")


@pytest.mark.ftr("FTR-FORMULA-FK-HELPER-PROVIDERS-P4A")
def test_lookup_formula_normalizes_lookup_intent_to_strings() -> None:
    formula = lookup_formula(
        source_key_column="id_(Customers)",
        lookup_sheet="Customers",
        lookup_key_column="id",
        lookup_value_column="name",
        missing=None,
    )

    assert formula == LookupFormulaSpec(
        source_key_column="id_(Customers)",
        lookup_sheet="Customers",
        lookup_key_column="id",
        lookup_value_column="name",
        missing="None",
    )
