"""Lookup formula provider construction for formula-mode FK helpers.

Behavior-preserving split out of the former single ``fk_helpers`` module
(FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-FK-HELPERS-P5).
"""
from __future__ import annotations

from typing import Any

from ....core.fk import FKDef
from spreadsheet_handling.core.formulas import lookup_formula


def _lookup_formula_provider(registry: dict[str, dict[str, Any]]):
    def provider(fk: FKDef, raw_ids: list[Any]) -> list[Any]:
        target = registry.get(fk.target_sheet_key) or {}
        lookup_sheet = str(target.get("sheet_name") or fk.target_sheet_key)
        formula = lookup_formula(
            source_key_column=fk.fk_column,
            lookup_sheet=lookup_sheet,
            lookup_key_column=fk.id_field,
            lookup_value_column=fk.value_field,
            missing="",
        )
        return [formula for _ in raw_ids]

    return provider
