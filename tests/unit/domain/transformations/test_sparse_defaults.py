from __future__ import annotations

import math

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.sparse_defaults import (
    sparse_collapse,
    sparse_expand,
)
from spreadsheet_handling.domain.transformations.xref_crosstable import contract_xref


pytestmark = pytest.mark.ftr("FTR-SPARSE-CROSSTABLE-COLLAPSE-P4A")


def test_sparse_collapse_replaces_default_values_in_configured_columns() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1", "f2"],
                "label": ["Currency", "Amount"],
                "P-001": ["nein", "ja"],
                "P-002": ["nein", "nein"],
            }
        )
    }

    out = sparse_collapse(
        frames,
        frame="matrix",
        default_value="nein",
        columns=["P-001", "P-002"],
    )

    assert out["matrix"].to_dict(orient="records") == [
        {"feature_id": "f1", "label": "Currency", "P-001": "", "P-002": ""},
        {"feature_id": "f2", "label": "Amount", "P-001": "ja", "P-002": ""},
    ]
    assert out["_meta"]["sparse_defaults"]["matrix"]["columns"] == ["P-001", "P-002"]
    assert out["_meta"]["sparse_defaults"]["matrix"]["default_value"] == "nein"


def test_sparse_expand_fills_blank_values_in_configured_columns() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1", "f2"],
                "P-001": ["", "ja"],
                "P-002": [None, pd.NA],
            }
        )
    }

    out = sparse_expand(
        frames,
        frame="matrix",
        default_value="nein",
        columns=["P-001", "P-002"],
    )

    assert out["matrix"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "nein", "P-002": "nein"},
        {"feature_id": "f2", "P-001": "ja", "P-002": "nein"},
    ]


def test_sparse_roundtrip_uses_metadata_when_expand_config_is_omitted() -> None:
    source = pd.DataFrame(
        {
            "feature_id": ["f1", "f2"],
            "P-001": ["nein", "ja"],
            "P-002": ["ja", "nein"],
        }
    )
    collapsed = sparse_collapse(
        {"matrix": source},
        frame="matrix",
        default_value="nein",
        columns=["P-001", "P-002"],
    )

    out = sparse_expand(collapsed, frame="matrix")

    pd.testing.assert_frame_equal(out["matrix"], source)


def test_sparse_collapse_defaults_to_xref_matrix_columns_when_available() -> None:
    contracted = contract_xref(
        {
            "long": pd.DataFrame(
                [
                    {"feature_id": "f1", "column_key": "P-001", "value": "nein"},
                    {"feature_id": "f1", "column_key": "P-002", "value": "ja"},
                ]
            )
        },
        relation="long",
        output="matrix",
        row_keys=["feature_id"],
        column_keys=["P-001", "P-002"],
    )

    out = sparse_collapse(contracted, frame="matrix", default_value="nein")

    assert out["matrix"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "", "P-002": "ja"},
    ]


def test_sparse_collapse_requires_columns_when_xref_metadata_is_missing() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["nein"],
                "P-001": ["nein"],
            }
        )
    }

    with pytest.raises(ValueError, match="requires explicit columns"):
        sparse_collapse(frames, frame="matrix", default_value="nein")


def test_sparse_collapse_rejects_ambiguous_xref_matrix_metadata() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "P-001": ["nein"],
                "P-002": ["ja"],
                "P-003": ["nein"],
            }
        ),
        "_meta": {
            "xref_crosstable": {
                "product_feature_xref": {
                    "matrix": "matrix",
                    "column_keys": ["P-001", "P-002"],
                },
                "other_product_feature_xref": {
                    "matrix": "matrix",
                    "column_keys": ["P-003"],
                },
            }
        },
    }

    with pytest.raises(ValueError, match="Ambiguous xref_crosstable metadata"):
        sparse_collapse(frames, frame="matrix", default_value="nein")


def test_sparse_expand_requires_columns_when_metadata_is_missing() -> None:
    frames = {"matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": [""]})}

    with pytest.raises(ValueError, match="requires explicit columns"):
        sparse_expand(frames, frame="matrix", default_value="nein")


def test_sparse_collapse_errors_on_preexisting_blank_conflicts() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1", "f2", "f3"],
                "P-001": ["", None, math.nan],
            }
        )
    }

    with pytest.raises(ValueError, match="contains blank cells"):
        sparse_collapse(
            frames,
            frame="matrix",
            default_value="nein",
            columns=["P-001"],
        )


def test_sparse_collapse_can_warn_or_ignore_blank_conflicts() -> None:
    frames = {"matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": [""]})}

    with pytest.warns(UserWarning, match="contains blank cells"):
        sparse_collapse(
            frames,
            frame="matrix",
            default_value="nein",
            columns=["P-001"],
            on_conflict="warn",
        )

    out = sparse_collapse(
        frames,
        frame="matrix",
        default_value="nein",
        columns=["P-001"],
        on_conflict="ignore",
    )

    assert out["matrix"].to_dict(orient="records") == [{"feature_id": "f1", "P-001": ""}]


def test_sparse_expand_supports_custom_blank_placeholder() -> None:
    frames = {"matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["<DEFAULT>"]})}

    out = sparse_expand(
        frames,
        frame="matrix",
        default_value="nein",
        blank_value="<DEFAULT>",
        columns=["P-001"],
    )

    assert out["matrix"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "nein"},
    ]


@pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")
class TestSparseAmbiguityCountsAllFrameMatches:
    """Uniform family policy: every mapping entry claiming the matrix counts.

    Partial entries (without a usable column_keys payload) participate in
    ambiguity; there is no usable-payload precedence.
    """

    @staticmethod
    def _matrix_frames(meta_entries: dict) -> dict:
        return {
            "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["nein"]}),
            "_meta": {"xref_crosstable": meta_entries},
        }

    def test_one_complete_and_one_partial_entry_fail(self) -> None:
        frames = self._matrix_frames(
            {
                "complete": {"matrix": "matrix", "column_keys": ["P-001"]},
                "partial": {"matrix": "matrix"},
            }
        )

        with pytest.raises(ValueError, match="Ambiguous xref_crosstable metadata"):
            sparse_collapse(frames, frame="matrix", default_value="nein")

    def test_two_partial_entries_fail(self) -> None:
        frames = self._matrix_frames(
            {
                "partial_a": {"matrix": "matrix"},
                "partial_b": {"matrix": "matrix", "row_keys": ["feature_id"]},
            }
        )

        with pytest.raises(ValueError, match="Ambiguous xref_crosstable metadata"):
            sparse_collapse(frames, frame="matrix", default_value="nein")

    def test_single_partial_entry_still_requires_explicit_columns(self) -> None:
        frames = self._matrix_frames({"partial": {"matrix": "matrix"}})

        with pytest.raises(ValueError, match="requires explicit columns"):
            sparse_collapse(frames, frame="matrix", default_value="nein")

    def test_preferred_exact_config_id_bypasses_frame_matching(self) -> None:
        frames = self._matrix_frames(
            {
                "matrix": {"matrix": "matrix", "column_keys": ["P-001"]},
                "other": {"matrix": "matrix", "column_keys": ["P-001"]},
            }
        )

        out = sparse_collapse(frames, frame="matrix", default_value="nein")

        assert out["matrix"]["P-001"].tolist() == [""]
