"""Shared private cell-value primitives for domain transformations.

Houses the small set of cell helpers that have been verbatim-identical across
multiple domain modules. Centralising them removes silent drift risk; the
implementations are byte-for-byte the originals, only relocated.

Out of scope (intentionally kept local to their owners): ``_plain_value`` (at
least three incompatible semantics across the domain), the extended
``_values_equal`` in ``sparse_defaults`` (missing-scalar short-circuit), and
the ``discriminator_split/values.py`` package-local core (its docstring
explicitly declines promotion).
"""
from __future__ import annotations

from typing import Any

import pandas as pd


def _is_empty_cell(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _values_equal(left: Any, right: Any) -> bool:
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False
