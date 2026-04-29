from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, TypeAlias


@dataclass(frozen=True)
class ListLiteralFormulaSpec:
    """Backend-neutral intent for a literal list validation formula."""

    values: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(str(value) for value in self.values))


@dataclass(frozen=True)
class LookupFormulaSpec:
    """Backend-neutral intent for a same-row lookup helper formula."""

    source_key_column: str
    lookup_sheet: str
    lookup_key_column: str
    lookup_value_column: str
    missing: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_key_column", str(self.source_key_column))
        object.__setattr__(self, "lookup_sheet", str(self.lookup_sheet))
        object.__setattr__(self, "lookup_key_column", str(self.lookup_key_column))
        object.__setattr__(self, "lookup_value_column", str(self.lookup_value_column))
        object.__setattr__(self, "missing", str(self.missing))


FormulaSpec: TypeAlias = ListLiteralFormulaSpec | LookupFormulaSpec


def list_literal_formula(values: Iterable[object]) -> ListLiteralFormulaSpec:
    return ListLiteralFormulaSpec(tuple(str(value) for value in values))


def lookup_formula(
    *,
    source_key_column: str,
    lookup_sheet: str,
    lookup_key_column: str,
    lookup_value_column: str,
    missing: object = "",
) -> LookupFormulaSpec:
    return LookupFormulaSpec(
        source_key_column=str(source_key_column),
        lookup_sheet=str(lookup_sheet),
        lookup_key_column=str(lookup_key_column),
        lookup_value_column=str(lookup_value_column),
        missing=str(missing),
    )


def formula_list_values(formula: FormulaSpec) -> tuple[str, ...]:
    if isinstance(formula, ListLiteralFormulaSpec):
        return formula.values
    raise TypeError(f"Unsupported formula spec: {type(formula).__name__}")


__all__ = [
    "FormulaSpec",
    "ListLiteralFormulaSpec",
    "LookupFormulaSpec",
    "formula_list_values",
    "list_literal_formula",
    "lookup_formula",
]
