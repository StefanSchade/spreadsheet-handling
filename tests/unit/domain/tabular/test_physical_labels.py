"""Unit tests for the shared physical-frame column-label boundary.

Characterizes the shared contract reused by XRef and Cell Codec:
physical labels must be non-missing, hashable, uniquely and
deterministically comparable, and scalar-addressable -- but not
string-only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from spreadsheet_handling.domain.tabular import (
    ensure_unique_field_declaration,
    ensure_unique_physical_column_labels,
    is_scalar_addressable_label,
)

pytestmark = pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")


class TestEnsureUniquePhysicalColumnLabels:
    def test_ordinary_unique_strings_pass(self) -> None:
        frame = pd.DataFrame([[1, 2, 3]], columns=["a", "b", "c"])
        ensure_unique_physical_column_labels(frame, frame_name="f")

    def test_unique_numeric_labels_pass(self) -> None:
        # Physical labels are not required to be strings.
        frame = pd.DataFrame([[1, 2]], columns=["a", 7])
        ensure_unique_physical_column_labels(frame, frame_name="f")

    def test_unique_hashable_tuple_labels_pass(self) -> None:
        frame = pd.DataFrame(
            [[1, 2]],
            columns=[("aktiv", "Sparvertrag"), ("passiv", "Annuitätendarlehen")],
        )
        ensure_unique_physical_column_labels(frame, frame_name="f")

    def test_duplicate_strings_rejected(self) -> None:
        frame = pd.DataFrame([[1, 2]], columns=pd.Index(["a", "a"], dtype=object))
        with pytest.raises(ValueError, match="duplicate physical column label"):
            ensure_unique_physical_column_labels(frame, frame_name="f")

    def test_duplicate_tuple_labels_rejected(self) -> None:
        frame = pd.DataFrame([[1, 2]], columns=[("x", "y"), ("x", "y")])
        with pytest.raises(ValueError, match="duplicate physical column label"):
            ensure_unique_physical_column_labels(frame, frame_name="f")

    def test_missing_like_nan_rejected_first(self) -> None:
        frame = pd.DataFrame([[1, 2]], columns=pd.Index(["a", np.nan], dtype=object))
        with pytest.raises(ValueError, match="missing-like physical column label"):
            ensure_unique_physical_column_labels(frame, frame_name="f")

    def test_missing_like_pd_na_rejected(self) -> None:
        frame = pd.DataFrame([[1, 2]], columns=pd.Index(["a", pd.NA], dtype=object))
        with pytest.raises(ValueError, match="missing-like physical column label"):
            ensure_unique_physical_column_labels(frame, frame_name="f")

    def test_ambiguous_equality_array_rejected(self) -> None:
        frame = pd.DataFrame(
            [[1, 2]], columns=pd.Index(["a", np.array([1, 2])], dtype=object)
        )
        with pytest.raises(ValueError, match="ambiguous equality"):
            ensure_unique_physical_column_labels(frame, frame_name="f")

    def test_unhashable_list_rejected(self) -> None:
        frame = pd.DataFrame([[1, 2]], columns=pd.Index(["a", [1, 2]], dtype=object))
        with pytest.raises(ValueError, match="unhashable physical column label"):
            ensure_unique_physical_column_labels(frame, frame_name="f")


class TestIsScalarAddressableLabel:
    @pytest.mark.parametrize("label", ["a", 7, ("x", "y"), 0, "0"])
    def test_valid_labels(self, label: object) -> None:
        assert is_scalar_addressable_label(label) is True

    @pytest.mark.parametrize("label", [None, np.nan, pd.NA])
    def test_missing_labels(self, label: object) -> None:
        assert is_scalar_addressable_label(label) is False

    def test_unhashable_label(self) -> None:
        assert is_scalar_addressable_label([1, 2]) is False

    def test_ambiguous_label(self) -> None:
        assert is_scalar_addressable_label(np.array([1, 2])) is False


class TestEnsureUniqueFieldDeclaration:
    def test_unique_passes(self) -> None:
        ensure_unique_field_declaration(["a", "b"], field_name="group_by")

    def test_duplicate_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate field"):
            ensure_unique_field_declaration(["a", "a"], field_name="group_by")
