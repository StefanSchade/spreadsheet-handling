from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, TypeAlias


@dataclass(frozen=True)
class ListLiteralFormulaSpec:
    """Backend-neutral intent for a literal list validation formula."""

    values: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(str(value) for value in self.values))


FormulaSpec: TypeAlias = ListLiteralFormulaSpec


def list_literal_formula(values: Iterable[object]) -> ListLiteralFormulaSpec:
    return ListLiteralFormulaSpec(tuple(str(value) for value in values))


def formula_list_values(formula: FormulaSpec) -> tuple[str, ...]:
    if isinstance(formula, ListLiteralFormulaSpec):
        return formula.values
    raise TypeError(f"Unsupported formula spec: {type(formula).__name__}")


__all__ = [
    "FormulaSpec",
    "ListLiteralFormulaSpec",
    "formula_list_values",
    "list_literal_formula",
]
