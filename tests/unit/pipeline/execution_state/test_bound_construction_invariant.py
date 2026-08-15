"""E4 root construction invariant (FTR section 18; independent E4
implementation review `9feb324`, section 18.4, CRITICAL).

A prior correction pass deep-froze ``kwargs`` only inside a separate
``BoundFramesTargetCall.bind(...)`` classmethod. The public,
dataclass-generated ``BoundFramesTargetCall(target, kwargs)`` constructor
remained a second, unfrozen construction path -- and ``resolve_trusted_call``
accepts *any* object satisfying ``type(step.fn) is BoundFramesTargetCall``
and ``step.fn.target is expected_target``, regardless of which path built it.
A caller-held mutable ``kwargs`` dict (or a nested alias inside it, or a
``MappingProxyType`` wrapping a still-live dict) passed directly to the
constructor could still be mutated after certification, changing execution
while the already-issued certificate stayed unchanged.

``bind()`` is removed. ``BoundFramesTargetCall.__post_init__`` now
unconditionally deep-freezes ``kwargs`` via ``_freeze_effective_kwargs``, so
the invariant lives at the ONE construction boundary every accepted instance
passes through -- there is no "safe" and "unsafe" constructor. These tests
reproduce the review's exact three bypasses and prove all three are closed,
plus the arbitrary-``Mapping``-rejection rule this correction also
establishes.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType
from typing import Any

import pandas as pd
import pytest

from spreadsheet_handling.core.formulas import LookupFormulaSpec
from spreadsheet_handling.domain.transformations.enrich_lookup import enrich_lookup
from spreadsheet_handling.pipeline.execution_state import (
    FormulaHelperCertificate,
    classify_formula_helper_step,
)
from spreadsheet_handling.pipeline.types import BoundFramesTargetCall, BoundStep

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _certifiable_kwargs(**overrides: object) -> dict:
    kwargs = {
        "source": "orders",
        "lookup": "products",
        "output": "orders",
        "key": "product_id",
        "helpers": {"fields": ["value"]},
        "missing": "empty",
        "helper_value_mode": "formula",
    }
    kwargs.update(overrides)
    return kwargs


def _frames() -> dict:
    return {
        "orders": pd.DataFrame({"product_id": ["p1"]}),
        "products": pd.DataFrame({"product_id": ["p1"], "value": ["v1"]}),
    }


def test_a_direct_constructor_with_mutable_dict_is_disconnected_from_the_original() -> None:
    """Task section 10.A -- the review's exact bypass A."""
    original = _certifiable_kwargs()
    call = BoundFramesTargetCall(enrich_lookup, original)

    assert type(call.kwargs) is MappingProxyType
    assert call.kwargs is not original

    step = BoundStep(name="manual", config={}, fn=call)
    certificate = classify_formula_helper_step(step)
    assert isinstance(certificate, FormulaHelperCertificate)

    original["helper_value_mode"] = "values"

    out = step(_frames())
    assert isinstance(out["orders"]["value"].iloc[0], LookupFormulaSpec)
    assert classify_formula_helper_step(step) == certificate


def test_b_direct_constructor_with_nested_caller_alias_is_disconnected() -> None:
    """Task section 10.B -- the review's exact bypass (a)."""
    fields = ["value"]
    call = BoundFramesTargetCall(enrich_lookup, _certifiable_kwargs(helpers={"fields": fields}))
    step = BoundStep(name="manual", config={}, fn=call)
    certificate = classify_formula_helper_step(step)
    assert isinstance(certificate, FormulaHelperCertificate)

    fields.append("code")

    out = step(_frames())
    formula_columns = [
        column for column in out["orders"].columns
        if isinstance(out["orders"][column].iloc[0], LookupFormulaSpec)
    ]
    assert formula_columns == ["value"]
    assert classify_formula_helper_step(step) == certificate


def test_c_mappingproxytype_over_a_caller_owned_live_dict_is_disconnected() -> None:
    """Task section 10.C -- the review's exact bypass (b)."""
    underlying = _certifiable_kwargs()
    proxy = MappingProxyType(underlying)
    call = BoundFramesTargetCall(enrich_lookup, proxy)
    step = BoundStep(name="manual", config={}, fn=call)
    certificate = classify_formula_helper_step(step)
    assert isinstance(certificate, FormulaHelperCertificate)

    underlying["helper_value_mode"] = "values"

    out = step(_frames())
    assert isinstance(out["orders"]["value"].iloc[0], LookupFormulaSpec)
    assert classify_formula_helper_step(step) == certificate


def test_d_mutation_through_the_directly_constructed_calls_own_view_is_rejected() -> None:
    call = BoundFramesTargetCall(enrich_lookup, _certifiable_kwargs())

    with pytest.raises(TypeError):
        call.kwargs["helper_value_mode"] = "values"  # type: ignore[index]
    with pytest.raises(TypeError):
        call.kwargs["helpers"]["fields"] = ("tampered",)  # type: ignore[index]


def test_e_target_and_kwargs_reassignment_on_a_directly_constructed_call_is_impossible() -> None:
    call = BoundFramesTargetCall(enrich_lookup, _certifiable_kwargs())

    with pytest.raises(FrozenInstanceError):
        call.target = enrich_lookup  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        call.kwargs = MappingProxyType({})  # type: ignore[misc]


def test_arbitrary_mapping_implementations_are_rejected_at_construction() -> None:
    """Task section 7: only exact `dict`/`MappingProxyType` are accepted at
    the root; any other Mapping implementation fails closed."""
    from collections.abc import Mapping

    class _CustomMapping(Mapping):
        def __init__(self, data: dict) -> None:
            self._data = data

        def __getitem__(self, key: str) -> Any:
            return self._data[key]

        def __iter__(self):
            return iter(self._data)

        def __len__(self) -> int:
            return len(self._data)

    with pytest.raises(TypeError, match="dict or MappingProxyType"):
        BoundFramesTargetCall(enrich_lookup, _CustomMapping(_certifiable_kwargs()))


def test_construction_freezes_unconditionally_regardless_of_keyword_style() -> None:
    # Positional and keyword construction both go through the same
    # __post_init__ -- there is exactly one invariant-establishing path.
    positional = BoundFramesTargetCall(enrich_lookup, _certifiable_kwargs())
    keyword = BoundFramesTargetCall(target=enrich_lookup, kwargs=_certifiable_kwargs())
    assert type(positional.kwargs) is MappingProxyType
    assert type(keyword.kwargs) is MappingProxyType


def test_genuine_copy_of_a_directly_constructed_call_still_certifies_and_executes_correctly() -> None:
    """Task section 12: copying/reusing an already-canonical
    ``BoundFramesTargetCall`` remains allowed and safe -- it necessarily
    executes the same immutable reviewed snapshot, no provenance check."""
    call = BoundFramesTargetCall(enrich_lookup, _certifiable_kwargs())
    copied_step = BoundStep(name="copied", config={}, fn=call)

    certificate = classify_formula_helper_step(copied_step)
    assert isinstance(certificate, FormulaHelperCertificate)

    out = copied_step(_frames())
    assert isinstance(out["orders"]["value"].iloc[0], LookupFormulaSpec)
