from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.xref_crosstable import (
    contract_xref,
    expand_xref,
)


pytestmark = pytest.mark.ftr("FTR-XREF-CROSSTABLE")
DENSE_FTR = pytest.mark.ftr("FTR-XREF-DENSE-AXES-P4A2")


class TestXRefFramesMetaBridgeContract:
    """Approved XRef contract: tuple/matrix addressing without value semantics."""

    def test_relation_rows_contract_into_matrix_cells(self) -> None:
        """Given relation rows, When contracted, Then values land at addresses."""
        # Given
        frames = {
            "relations": pd.DataFrame([
                {
                    "product": "home_automation",
                    "market": "JP",
                    "relation": "SaaS / JP / OIDC",
                },
                {
                    "product": "home_automation",
                    "market": "DE",
                    "relation": "OnPrem / DE / SAML",
                },
            ])
        }

        # When
        out = contract_xref(
            frames,
            relation="relations",
            output="matrix",
            row_keys=["product"],
            column_key="market",
            value="relation",
            column_keys=["JP", "DE", "US"],
        )

        # Then
        assert out["matrix"].to_dict(orient="records") == [
            {
                "product": "home_automation",
                "JP": "SaaS / JP / OIDC",
                "DE": "OnPrem / DE / SAML",
                "US": "",
            }
        ]

    def test_matrix_cells_expand_back_into_relation_rows(self) -> None:
        """Given non-empty matrix cells, When expanded, Then each becomes one row."""
        # Given
        frames = {
            "matrix": pd.DataFrame([
                {
                    "product": "home_automation",
                    "JP": "SaaS / JP / OIDC",
                    "DE": "OnPrem / DE / SAML",
                }
            ])
        }

        # When
        out = expand_xref(
            frames,
            matrix="matrix",
            output="relations",
            row_keys=["product"],
            value_columns=["JP", "DE"],
            column_key="market",
            value="relation",
        )

        # Then
        assert out["relations"].to_dict(orient="records") == [
            {
                "product": "home_automation",
                "market": "JP",
                "relation": "SaaS / JP / OIDC",
            },
            {
                "product": "home_automation",
                "market": "DE",
                "relation": "OnPrem / DE / SAML",
            },
        ]

    def test_drop_empty_true_means_empty_matrix_cell_has_no_relation_row(self) -> None:
        """Given drop_empty=True, When expanded, Then empty cells are omitted."""
        # Given
        frames = {
            "matrix": pd.DataFrame([
                {
                    "product": "home_automation",
                    "JP": "SaaS / JP / OIDC",
                    "DE": "",
                }
            ])
        }

        # When
        out = expand_xref(
            frames,
            matrix="matrix",
            output="relations",
            row_keys=["product"],
            value_columns=["JP", "DE"],
            column_key="market",
            value="relation",
            drop_empty=True,
        )

        # Then
        assert out["relations"].to_dict(orient="records") == [
            {
                "product": "home_automation",
                "market": "JP",
                "relation": "SaaS / JP / OIDC",
            }
        ]

    def test_drop_empty_false_preserves_empty_matrix_cell_as_empty_relation_row(self) -> None:
        """Given drop_empty=False, When expanded, Then empty cells are preserved."""
        # Given
        frames = {
            "matrix": pd.DataFrame([
                {
                    "product": "home_automation",
                    "JP": "SaaS / JP / OIDC",
                    "DE": "",
                }
            ])
        }

        # When
        out = expand_xref(
            frames,
            matrix="matrix",
            output="relations",
            row_keys=["product"],
            value_columns=["JP", "DE"],
            column_key="market",
            value="relation",
            drop_empty=False,
        )

        # Then
        assert out["relations"].to_dict(orient="records") == [
            {
                "product": "home_automation",
                "market": "JP",
                "relation": "SaaS / JP / OIDC",
            },
            {"product": "home_automation", "market": "DE", "relation": ""},
        ]

    def test_duplicate_tuple_coordinates_hard_fail(self) -> None:
        """Given duplicate coordinates, When contracted, Then XRef fails fast."""
        # Given
        frames = {
            "relations": pd.DataFrame([
                {"product": "home_automation", "market": "JP", "relation": "first"},
                {"product": "home_automation", "market": "JP", "relation": "second"},
            ])
        }

        # When / Then
        with pytest.raises(ValueError, match=r"(?i)duplicate.*row/column pair"):
            contract_xref(
                frames,
                relation="relations",
                output="matrix",
                row_keys=["product"],
                column_key="market",
                value="relation",
            )

    def test_axis_domains_survive_independently_of_filled_relation_cells(self) -> None:
        """Given dynamic axis domains, When contracted, Then empty addresses render."""
        # Given
        frames = {
            "products": pd.DataFrame({"product": ["home_automation", "security"]}),
            "markets": pd.DataFrame({"market": ["JP", "DE", "US"]}),
            "relations": pd.DataFrame([
                {
                    "product": "home_automation",
                    "market": "JP",
                    "relation": "SaaS / JP / OIDC",
                }
            ]),
        }

        # When
        out = contract_xref(
            frames,
            relation="relations",
            output="matrix",
            row_keys=["product"],
            column_key="market",
            value="relation",
            dense_axes={
                "rows_from": {"frame": "products", "key": "product"},
                "columns_from": {"frame": "markets", "key": "market"},
            },
        )

        # Then
        assert out["matrix"].to_dict(orient="records") == [
            {
                "product": "home_automation",
                "JP": "SaaS / JP / OIDC",
                "DE": "",
                "US": "",
            },
            {"product": "security", "JP": "", "DE": "", "US": ""},
        ]

    def test_relation_values_are_transport_not_xref_semantics(self) -> None:
        """Given parseable-looking strings, When roundtripped, Then text is unchanged."""
        # Given
        rows = [
            {"product": "home_automation", "market": "JP", "relation": "TRUE"},
            {
                "product": "home_automation",
                "market": "DE",
                "relation": "SaaS / JP / OIDC",
            },
            {"product": "security", "market": "JP", "relation": "A-B-C"},
            {
                "product": "security",
                "market": "DE",
                "relation": "please check with customer",
            },
        ]
        frames = {"relations": pd.DataFrame(rows)}

        # When
        contracted = contract_xref(
            frames,
            relation="relations",
            output="matrix",
            row_keys=["product"],
            column_key="market",
            value="relation",
            column_keys=["JP", "DE"],
        )
        out = expand_xref(
            contracted,
            matrix="matrix",
            output="roundtrip",
            row_keys=["product"],
            value_columns=["JP", "DE"],
            column_key="market",
            value="relation",
        )

        # Then
        assert out["roundtrip"].to_dict(orient="records") == rows


def test_expand_xref_turns_matrix_columns_into_long_rows() -> None:
    frames = {
        "product_matrix": pd.DataFrame({
            "feature_id": ["f1", "f2"],
            "label": ["Currency", "Amount"],
            "P-001": ["E", "S"],
            "P-002": ["E-R-K", ""],
        })
    }

    out = expand_xref(
        frames,
        matrix="product_matrix",
        output="feature_product_codes",
        row_keys=["feature_id"],
        value_columns=["P-001", "P-002"],
    )

    assert out["feature_product_codes"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "value": "E"},
        {"feature_id": "f1", "column_key": "P-002", "value": "E-R-K"},
        {"feature_id": "f2", "column_key": "P-001", "value": "S"},
        {"feature_id": "f2", "column_key": "P-002", "value": ""},
    ]
    assert out["_meta"]["xref_crosstable"]["feature_product_codes"]["column_keys"] == [
        "P-001",
        "P-002",
    ]


def test_expand_xref_can_drop_empty_cells_for_sparse_relation() -> None:
    frames = {
        "matrix": pd.DataFrame({
            "feature_id": ["f1", "f2"],
            "P-001": ["E", ""],
        })
    }

    out = expand_xref(
        frames,
        matrix="matrix",
        output="long",
        row_keys="feature_id",
        value_columns=["P-001"],
        drop_empty=True,
    )

    assert out["long"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "value": "E"},
    ]


def test_contract_xref_turns_long_rows_back_into_matrix_using_meta_column_order() -> None:
    frames = {
        "product_matrix": pd.DataFrame({
            "feature_id": ["f1", "f2"],
            "P-001": ["E", "S"],
            "P-002": ["E-R-K", ""],
        })
    }
    expanded = expand_xref(
        frames,
        matrix="product_matrix",
        output="feature_product_codes",
        row_keys=["feature_id"],
        value_columns=["P-001", "P-002"],
    )

    out = contract_xref(
        expanded,
        relation="feature_product_codes",
        output="product_matrix_roundtrip",
        row_keys=["feature_id"],
    )

    assert out["product_matrix_roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E", "P-002": "E-R-K"},
        {"feature_id": "f2", "P-001": "S", "P-002": ""},
    ]


def test_named_xref_config_roundtrips_column_order() -> None:
    frames = {
        "product_matrix": pd.DataFrame({
            "feature_id": ["f1"],
            "P-001": ["E"],
            "P-002": ["S"],
        })
    }
    expanded = expand_xref(
        frames,
        matrix="product_matrix",
        output="long",
        row_keys=["feature_id"],
        value_columns=["P-001", "P-002"],
        name="product_feature_xref",
    )

    out = contract_xref(
        expanded,
        relation="long",
        output="roundtrip",
        row_keys=["feature_id"],
        name="product_feature_xref",
    )

    assert list(out["roundtrip"].columns) == ["feature_id", "P-001", "P-002"]
    assert out["roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E", "P-002": "S"},
    ]


def test_unknown_named_xref_config_falls_back_to_relation_column_order() -> None:
    frames = {
        "long": pd.DataFrame([
            {"feature_id": "f1", "column_key": "P-002", "value": "S"},
            {"feature_id": "f1", "column_key": "P-001", "value": "E"},
        ]),
        "_meta": {
            "xref_crosstable": {
                "product_feature_xref": {
                    "column_keys": ["P-001", "P-002"],
                }
            }
        },
    }

    out = contract_xref(
        frames,
        relation="long",
        output="roundtrip",
        row_keys=["feature_id"],
        name="missing_config",
    )

    assert list(out["roundtrip"].columns) == ["feature_id", "P-002", "P-001"]
    assert out["roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-002": "S", "P-001": "E"},
    ]


def test_contract_xref_rejects_duplicate_row_column_pairs() -> None:
    frames = {
        "long": pd.DataFrame([
            {"feature_id": "f1", "column_key": "P-001", "value": "E"},
            {"feature_id": "f1", "column_key": "P-001", "value": "S"},
        ])
    }

    with pytest.raises(ValueError, match="Duplicate xref"):
        contract_xref(
            frames,
            relation="long",
            output="matrix",
            row_keys=["feature_id"],
        )


def test_roundtrip_does_not_require_visible_labels_for_identity() -> None:
    frames = {
        "product_matrix": pd.DataFrame({
            "feature_id": ["f1", "f2"],
            "label": ["Same visible label", "Same visible label"],
            "P-001": ["E", "S"],
        })
    }

    expanded = expand_xref(
        frames,
        matrix="product_matrix",
        output="long",
        row_keys=["feature_id"],
        value_columns=["P-001"],
    )
    out = contract_xref(
        expanded,
        relation="long",
        output="roundtrip",
        row_keys=["feature_id"],
    )

    assert out["roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E"},
        {"feature_id": "f2", "P-001": "S"},
    ]


@pytest.mark.ftr("FTR-COMPACT-TRANSFORM-API-ERGONOMICS-P4")
def test_missing_value_columns_error_names_configured_field() -> None:
    frames = {
        "matrix": pd.DataFrame({
            "feature_id": ["f1"],
            "P-001": ["E"],
        })
    }

    with pytest.raises(KeyError, match="configured value_columns"):
        expand_xref(
            frames,
            matrix="matrix",
            output="long",
            row_keys=["feature_id"],
            value_columns=["P-002"],
        )


def test_expand_xref_rejects_multiindex_columns_in_first_slice() -> None:
    frames = {
        "matrix": pd.DataFrame(
            [["f1", "E"]],
            columns=pd.MultiIndex.from_tuples([
                ("feature", "id"),
                ("product", "P-001"),
            ]),
        )
    }

    with pytest.raises(ValueError, match="MultiIndex"):
        expand_xref(
            frames,
            matrix="matrix",
            output="long",
            row_keys=[("feature", "id")],
            value_columns=[("product", "P-001")],
        )


def test_contract_xref_rejects_tuple_column_keys_in_first_slice() -> None:
    frames = {
        "long": pd.DataFrame([
            {"feature_id": "f1", "column_key": ("product", "P-001"), "value": "E"},
        ])
    }

    # Tuples now fail the carrier-stable column-identity contract (before
    # the flat-label check is even reached).
    with pytest.raises(ValueError, match="non-empty string column"):
        contract_xref(
            frames,
            relation="long",
            output="matrix",
            row_keys=["feature_id"],
        )


@DENSE_FTR
def test_contract_xref_dense_rows_from_external_axis() -> None:
    frames = {
        "resources": pd.DataFrame({"resource_key": ["r1", "r2"]}),
        "values": pd.DataFrame([
            {"resource_key": "r1", "context_id": "default", "text": "Hello"},
        ]),
    }

    out = contract_xref(
        frames,
        relation="values",
        output="matrix",
        row_keys=["resource_key"],
        column_key="context_id",
        value="text",
        column_keys=["default", "product_a"],
        dense_axes={
            "rows_from": {"frame": "resources", "key": "resource_key"},
        },
        name="resource_contexts",
    )

    assert out["matrix"].to_dict(orient="records") == [
        {"resource_key": "r1", "default": "Hello", "product_a": ""},
        {"resource_key": "r2", "default": "", "product_a": ""},
    ]
    assert out["_meta"]["xref_crosstable"]["resource_contexts"]["dense_axes"] == {
        "rows_from": {"frame": "resources", "key": "resource_key"},
        "resolved": {
            "row_identities": [
                {"resource_key": "r1"},
                {"resource_key": "r2"},
            ],
        },
    }


@DENSE_FTR
def test_contract_xref_dense_rows_and_columns_from_external_axes() -> None:
    frames = {
        "resources": pd.DataFrame({"resource_key": ["r1", "r2"]}),
        "contexts": pd.DataFrame({"context_id": ["default", "product_a", "product_b"]}),
        "values": pd.DataFrame([
            {"resource_key": "r1", "context_id": "default", "text": "Hello"},
        ]),
    }

    out = contract_xref(
        frames,
        relation="values",
        output="matrix",
        row_keys=["resource_key"],
        column_key="context_id",
        value="text",
        dense_axes={
            "rows_from": {"frame": "resources", "key": "resource_key"},
            "columns_from": {"frame": "contexts", "key": "context_id"},
        },
        name="resource_contexts",
    )

    assert list(out["matrix"].columns) == [
        "resource_key",
        "default",
        "product_a",
        "product_b",
    ]
    assert out["matrix"].to_dict(orient="records") == [
        {"resource_key": "r1", "default": "Hello", "product_a": "", "product_b": ""},
        {"resource_key": "r2", "default": "", "product_a": "", "product_b": ""},
    ]


@DENSE_FTR
def test_contract_xref_empty_relation_produces_configured_dense_shape() -> None:
    frames = {
        "resources": pd.DataFrame({"resource_key": ["r1", "r2"]}),
        "contexts": pd.DataFrame({"context_id": ["default", "product_a"]}),
        "values": pd.DataFrame(columns=["resource_key", "context_id", "text"]),
    }

    out = contract_xref(
        frames,
        relation="values",
        output="matrix",
        row_keys=["resource_key"],
        column_key="context_id",
        value="text",
        dense_axes={
            "rows_from": {"frame": "resources", "key": "resource_key"},
            "columns_from": {"frame": "contexts", "key": "context_id"},
        },
        name="resource_contexts",
    )

    assert out["matrix"].to_dict(orient="records") == [
        {"resource_key": "r1", "default": "", "product_a": ""},
        {"resource_key": "r2", "default": "", "product_a": ""},
    ]


@DENSE_FTR
def test_expand_contract_roundtrip_preserves_dense_shape_from_metadata() -> None:
    frames = {
        "resources": pd.DataFrame({"resource_key": ["r1", "r2"]}),
        "contexts": pd.DataFrame({"context_id": ["default", "product_a"]}),
        "values": pd.DataFrame([
            {"resource_key": "r1", "context_id": "default", "text": "Hello"},
        ]),
    }
    contracted = contract_xref(
        frames,
        relation="values",
        output="matrix",
        row_keys=["resource_key"],
        column_key="context_id",
        value="text",
        dense_axes={
            "rows_from": {"frame": "resources", "key": "resource_key"},
            "columns_from": {"frame": "contexts", "key": "context_id"},
        },
        name="resource_contexts",
    )
    expanded = expand_xref(
        {"matrix": contracted["matrix"], "_meta": contracted["_meta"]},
        matrix="matrix",
        output="values_roundtrip",
        row_keys=["resource_key"],
        value_columns=["default", "product_a"],
        column_key="context_id",
        value="text",
        name="resource_contexts",
    )

    out = contract_xref(
        {"values_roundtrip": expanded["values_roundtrip"], "_meta": expanded["_meta"]},
        relation="values_roundtrip",
        output="matrix_roundtrip",
        row_keys=["resource_key"],
        column_key="context_id",
        value="text",
        name="resource_contexts",
    )

    assert expanded["_meta"]["xref_crosstable"]["resource_contexts"]["dense_axes"]
    assert out["matrix_roundtrip"].to_dict(orient="records") == [
        {"resource_key": "r1", "default": "Hello", "product_a": ""},
        {"resource_key": "r2", "default": "", "product_a": ""},
    ]


@DENSE_FTR
def test_contract_xref_reuses_stored_dense_axes_without_source_frames() -> None:
    frames = {
        "resources": pd.DataFrame({"resource_key": ["r1", "r2"]}),
        "contexts": pd.DataFrame({"context_id": ["default", "product_a"]}),
        "values": pd.DataFrame(columns=["resource_key", "context_id", "text"]),
    }
    contracted = contract_xref(
        frames,
        relation="values",
        output="matrix",
        row_keys=["resource_key"],
        column_key="context_id",
        value="text",
        dense_axes={
            "rows_from": {"frame": "resources", "key": "resource_key"},
            "columns_from": {"frame": "contexts", "key": "context_id"},
        },
        name="resource_contexts",
    )

    out = contract_xref(
        {
            "values": pd.DataFrame(columns=["resource_key", "context_id", "text"]),
            "_meta": contracted["_meta"],
        },
        relation="values",
        output="matrix",
        row_keys=["resource_key"],
        column_key="context_id",
        value="text",
        name="resource_contexts",
    )

    assert out["matrix"].to_dict(orient="records") == [
        {"resource_key": "r1", "default": "", "product_a": ""},
        {"resource_key": "r2", "default": "", "product_a": ""},
    ]


@DENSE_FTR
def test_contract_xref_without_dense_axes_keeps_sparse_shape() -> None:
    frames = {
        "resources": pd.DataFrame({"resource_key": ["r1", "r2"]}),
        "contexts": pd.DataFrame({"context_id": ["default", "product_a"]}),
        "values": pd.DataFrame([
            {"resource_key": "r1", "context_id": "default", "text": "Hello"},
        ]),
    }

    out = contract_xref(
        frames,
        relation="values",
        output="matrix",
        row_keys=["resource_key"],
        column_key="context_id",
        value="text",
    )

    assert out["matrix"].to_dict(orient="records") == [
        {"resource_key": "r1", "default": "Hello"},
    ]
    assert "dense_axes" not in out["_meta"]["xref_crosstable"]["values"]


@DENSE_FTR
def test_contract_xref_rejects_duplicate_dense_axis_keys() -> None:
    frames = {
        "resources": pd.DataFrame({"resource_key": ["r1", "r1"]}),
        "values": pd.DataFrame(columns=["resource_key", "context_id", "text"]),
    }

    with pytest.raises(ValueError, match="duplicate key"):
        contract_xref(
            frames,
            relation="values",
            output="matrix",
            row_keys=["resource_key"],
            column_key="context_id",
            value="text",
            column_keys=["default"],
            dense_axes={
                "rows_from": {"frame": "resources", "key": "resource_key"},
            },
        )


@DENSE_FTR
def test_contract_xref_dense_axis_requires_explicit_source_key() -> None:
    frames = {
        "resources": pd.DataFrame({"resource_key": ["r1"]}),
        "values": pd.DataFrame(columns=["resource_key", "context_id", "text"]),
    }

    with pytest.raises(ValueError, match="key or keys explicitly"):
        contract_xref(
            frames,
            relation="values",
            output="matrix",
            row_keys=["resource_key"],
            column_key="context_id",
            value="text",
            column_keys=["default"],
            dense_axes={
                "rows_from": {"frame": "resources"},
            },
        )


@DENSE_FTR
def test_contract_xref_rejects_tuples_outside_configured_dense_axes() -> None:
    frames = {
        "resources": pd.DataFrame({"resource_key": ["r1"]}),
        "contexts": pd.DataFrame({"context_id": ["default"]}),
        "values": pd.DataFrame([
            {"resource_key": "r2", "context_id": "default", "text": "Outside row"},
            {"resource_key": "r1", "context_id": "other", "text": "Outside column"},
        ]),
    }

    with pytest.raises(ValueError, match="outside dense_axes.rows_from"):
        contract_xref(
            frames,
            relation="values",
            output="matrix",
            row_keys=["resource_key"],
            column_key="context_id",
            value="text",
            dense_axes={
                "rows_from": {"frame": "resources", "key": "resource_key"},
                "columns_from": {"frame": "contexts", "key": "context_id"},
            },
        )


# ---------------------------------------------------------------------------
# FTR-XREF-CROSSTABLE Slice A -- characterization tests before runtime changes
# ---------------------------------------------------------------------------


class TestExpandXrefBlankCellBehavior:
    """Characterize drop_empty behavior as a named invariant before Slice D.

    Slice D (scoped recomposition) will change what happens to blank cells in
    an out-of-scope vs in-scope context.  These tests lock the *current*
    behavior of expand_xref in isolation so that any change is deliberate.
    """

    def test_drop_empty_false_emits_row_for_blank_cell(self) -> None:
        frames = {
            "matrix": pd.DataFrame({
                "row_key": ["r1"],
                "col_A": [""],
            })
        }
        out = expand_xref(
            frames,
            matrix="matrix",
            output="relation",
            row_keys=["row_key"],
            value_columns=["col_A"],
            drop_empty=False,
        )
        assert out["relation"].to_dict(orient="records") == [
            {"row_key": "r1", "column_key": "col_A", "value": ""},
        ]

    def test_drop_empty_true_omits_row_for_blank_cell(self) -> None:
        frames = {
            "matrix": pd.DataFrame({
                "row_key": ["r1", "r2"],
                "col_A": ["present", ""],
            })
        }
        out = expand_xref(
            frames,
            matrix="matrix",
            output="relation",
            row_keys=["row_key"],
            value_columns=["col_A"],
            drop_empty=True,
        )
        assert out["relation"].to_dict(orient="records") == [
            {"row_key": "r1", "column_key": "col_A", "value": "present"},
        ]

    def test_drop_empty_default_matches_false(self) -> None:
        frames = {
            "matrix": pd.DataFrame({
                "row_key": ["r1"],
                "col_A": [""],
            })
        }
        out_false = expand_xref(
            frames,
            matrix="matrix",
            output="relation",
            row_keys=["row_key"],
            value_columns=["col_A"],
            drop_empty=False,
        )
        out_default = expand_xref(
            frames,
            matrix="matrix",
            output="relation",
            row_keys=["row_key"],
            value_columns=["col_A"],
        )
        assert (
            out_false["relation"].to_dict(orient="records")
            == out_default["relation"].to_dict(orient="records")
        )


@DENSE_FTR
class TestColumnKeysAndDenseColumnFromInteraction:
    """Characterize the interaction when both column_keys and dense_axes.columns_from
    are supplied.

    Actual behavior: a consistency check, not a precedence relationship.
    Both sources must agree on the same ordered list; if they disagree the step
    fails fast.  This documents the current contract before any surface change
    (Slice E).
    """

    def test_matching_column_keys_and_dense_columns_from_succeeds(self) -> None:
        frames = {
            "contexts": pd.DataFrame({"context_id": ["A", "B"]}),
            "values": pd.DataFrame(columns=["row_key", "context_id", "text"]),
        }
        out = contract_xref(
            frames,
            relation="values",
            output="matrix",
            row_keys=["row_key"],
            column_key="context_id",
            value="text",
            column_keys=["A", "B"],
            dense_axes={
                "columns_from": {"frame": "contexts", "key": "context_id"},
            },
            name="consistency_test",
        )
        assert list(out["matrix"].columns) == ["row_key", "A", "B"]

    def test_mismatched_column_keys_and_dense_columns_from_fails_fast(self) -> None:
        frames = {
            "contexts": pd.DataFrame({"context_id": ["A", "B", "C"]}),
            "values": pd.DataFrame(columns=["row_key", "context_id", "text"]),
        }
        with pytest.raises(ValueError, match="column_keys must match dense_axes.columns_from"):
            contract_xref(
                frames,
                relation="values",
                output="matrix",
                row_keys=["row_key"],
                column_key="context_id",
                value="text",
                column_keys=["A", "B"],
                dense_axes={
                    "columns_from": {"frame": "contexts", "key": "context_id"},
                },
                name="mismatch_test",
            )


# ---------------------------------------------------------------------------
# FTR-XREF-CROSSTABLE Slice D -- scoped recomposition via base_relation
# ---------------------------------------------------------------------------


class TestExpandXrefScopedRecomposition:
    """Test expand_xref scoped recomposition via the base_relation parameter.

    When base_relation is supplied, expand_xref performs scoped recomposition:
    in-scope matrix cells update the relation; out-of-scope base rows are
    preserved and appended after.  In-scope = all (row_identity × value_col)
    addresses present in the matrix frame, regardless of blank/nonblank.
    """

    def test_without_base_relation_behavior_unchanged(self) -> None:
        frames = {
            "matrix": pd.DataFrame({"row_key": ["r1"], "col_A": ["new"]}),
        }
        out = expand_xref(
            frames, matrix="matrix", output="rel",
            row_keys=["row_key"], value_columns=["col_A"],
        )
        assert out["rel"].to_dict(orient="records") == [
            {"row_key": "r1", "column_key": "col_A", "value": "new"},
        ]

    def test_nonblank_cell_replaces_matching_base_row(self) -> None:
        frames = {
            "matrix": pd.DataFrame({"row_key": ["r1"], "col_A": ["updated"]}),
            "base": pd.DataFrame([
                {"row_key": "r1", "column_key": "col_A", "value": "original"},
            ]),
        }
        out = expand_xref(
            frames, matrix="matrix", output="rel",
            row_keys=["row_key"], value_columns=["col_A"], base_relation="base",
        )
        assert out["rel"].to_dict(orient="records") == [
            {"row_key": "r1", "column_key": "col_A", "value": "updated"},
        ]

    def test_blank_cell_with_drop_empty_true_removes_matching_base_row(self) -> None:
        frames = {
            "matrix": pd.DataFrame({"row_key": ["r1"], "col_A": [""]}),
            "base": pd.DataFrame([
                {"row_key": "r1", "column_key": "col_A", "value": "original"},
            ]),
        }
        out = expand_xref(
            frames, matrix="matrix", output="rel",
            row_keys=["row_key"], value_columns=["col_A"],
            base_relation="base", drop_empty=True,
        )
        assert out["rel"].to_dict(orient="records") == []

    def test_blank_cell_with_drop_empty_false_emits_empty_row(self) -> None:
        frames = {
            "matrix": pd.DataFrame({"row_key": ["r1"], "col_A": [""]}),
            "base": pd.DataFrame([
                {"row_key": "r1", "column_key": "col_A", "value": "original"},
            ]),
        }
        out = expand_xref(
            frames, matrix="matrix", output="rel",
            row_keys=["row_key"], value_columns=["col_A"],
            base_relation="base", drop_empty=False,
        )
        assert out["rel"].to_dict(orient="records") == [
            {"row_key": "r1", "column_key": "col_A", "value": ""},
        ]

    def test_in_scope_address_with_no_base_counterpart_is_added(self) -> None:
        frames = {
            "matrix": pd.DataFrame({"row_key": ["r1", "r2"], "col_A": ["new", "also_new"]}),
            "base": pd.DataFrame([
                {"row_key": "r1", "column_key": "col_A", "value": "existing"},
            ]),
        }
        out = expand_xref(
            frames, matrix="matrix", output="rel",
            row_keys=["row_key"], value_columns=["col_A"], base_relation="base",
        )
        records = out["rel"].to_dict(orient="records")
        assert {"row_key": "r2", "column_key": "col_A", "value": "also_new"} in records

    def test_out_of_scope_base_row_preserved(self) -> None:
        """Base row at col_B is not in value_cols scope, so it is carried through."""
        frames = {
            "matrix": pd.DataFrame({"row_key": ["r1"], "col_A": ["updated"]}),
            "base": pd.DataFrame([
                {"row_key": "r1", "column_key": "col_A", "value": "old"},
                {"row_key": "r1", "column_key": "col_B", "value": "preserved"},
            ]),
        }
        out = expand_xref(
            frames, matrix="matrix", output="rel",
            row_keys=["row_key"], value_columns=["col_A"], base_relation="base",
        )
        records = out["rel"].to_dict(orient="records")
        assert {"row_key": "r1", "column_key": "col_B", "value": "preserved"} in records

    def test_blank_cell_address_is_in_scope_so_base_row_not_preserved(self) -> None:
        """A blank matrix cell is still in-scope; base row at that address is not kept."""
        frames = {
            "matrix": pd.DataFrame({"row_key": ["r1"], "col_A": [""]}),
            "base": pd.DataFrame([
                {"row_key": "r1", "column_key": "col_A", "value": "old"},
                {"row_key": "r1", "column_key": "col_B", "value": "out_of_scope"},
            ]),
        }
        out = expand_xref(
            frames, matrix="matrix", output="rel",
            row_keys=["row_key"], value_columns=["col_A"],
            base_relation="base", drop_empty=True,
        )
        records = out["rel"].to_dict(orient="records")
        assert {"row_key": "r1", "column_key": "col_A", "value": "old"} not in records
        assert {"row_key": "r1", "column_key": "col_B", "value": "out_of_scope"} in records

    def test_out_of_scope_base_rows_appended_after_in_scope_rows(self) -> None:
        frames = {
            "matrix": pd.DataFrame({"row_key": ["r1", "r2"], "col_A": ["a1", "a2"]}),
            "base": pd.DataFrame([
                {"row_key": "r3", "column_key": "col_A", "value": "out1"},
                {"row_key": "r4", "column_key": "col_A", "value": "out2"},
            ]),
        }
        out = expand_xref(
            frames, matrix="matrix", output="rel",
            row_keys=["row_key"], value_columns=["col_A"], base_relation="base",
        )
        assert out["rel"].to_dict(orient="records") == [
            {"row_key": "r1", "column_key": "col_A", "value": "a1"},
            {"row_key": "r2", "column_key": "col_A", "value": "a2"},
            {"row_key": "r3", "column_key": "col_A", "value": "out1"},
            {"row_key": "r4", "column_key": "col_A", "value": "out2"},
        ]

    def test_multiple_out_of_scope_rows_preserved_in_base_order(self) -> None:
        frames = {
            "matrix": pd.DataFrame({"row_key": ["r1"], "col_A": ["a1"]}),
            "base": pd.DataFrame([
                {"row_key": "r1", "column_key": "col_A", "value": "in_scope"},
                {"row_key": "r1", "column_key": "col_B", "value": "b1"},
                {"row_key": "r2", "column_key": "col_B", "value": "b2"},
                {"row_key": "r3", "column_key": "col_B", "value": "b3"},
            ]),
        }
        out = expand_xref(
            frames, matrix="matrix", output="rel",
            row_keys=["row_key"], value_columns=["col_A"], base_relation="base",
        )
        records = out["rel"].to_dict(orient="records")
        assert records[0] == {"row_key": "r1", "column_key": "col_A", "value": "a1"}
        assert records[1] == {"row_key": "r1", "column_key": "col_B", "value": "b1"}
        assert records[2] == {"row_key": "r2", "column_key": "col_B", "value": "b2"}
        assert records[3] == {"row_key": "r3", "column_key": "col_B", "value": "b3"}

    def test_missing_base_frame_fails_fast(self) -> None:
        frames = {
            "matrix": pd.DataFrame({"row_key": ["r1"], "col_A": ["a"]}),
        }
        with pytest.raises(KeyError):
            expand_xref(
                frames, matrix="matrix", output="rel",
                row_keys=["row_key"], value_columns=["col_A"],
                base_relation="nonexistent",
            )

    def test_base_frame_missing_required_column_fails_fast(self) -> None:
        frames = {
            "matrix": pd.DataFrame({"row_key": ["r1"], "col_A": ["a"]}),
            "base": pd.DataFrame([{"row_key": "r1", "wrong_col": "something"}]),
        }
        with pytest.raises(KeyError):
            expand_xref(
                frames, matrix="matrix", output="rel",
                row_keys=["row_key"], value_columns=["col_A"],
                base_relation="base",
            )


@DENSE_FTR
def test_contract_xref_dense_multicolumn_row_keys() -> None:
    frames = {
        "products": pd.DataFrame({
            "region": ["NA", "EMEA"],
            "category": ["A", "B"],
        }),
        "contexts": pd.DataFrame({"context_id": ["default", "product_a"]}),
        "values": pd.DataFrame([
            {
                "region": "NA",
                "category": "A",
                "context_id": "default",
                "text": "NA-A Default",
            },
        ]),
    }

    out = contract_xref(
        frames,
        relation="values",
        output="matrix",
        row_keys=["region", "category"],
        column_key="context_id",
        value="text",
        dense_axes={
            "rows_from": {"frame": "products", "keys": ["region", "category"]},
            "columns_from": {"frame": "contexts", "key": "context_id"},
        },
        name="multicolumn_dense",
    )

    assert out["matrix"].to_dict(orient="records") == [
        {"region": "NA", "category": "A", "default": "NA-A Default", "product_a": ""},
        {"region": "EMEA", "category": "B", "default": "", "product_a": ""},
    ]
    assert out["_meta"]["xref_crosstable"]["multicolumn_dense"]["dense_axes"] == {
        "rows_from": {"frame": "products", "keys": ["region", "category"]},
        "columns_from": {"frame": "contexts", "key": "context_id"},
        "resolved": {
            "row_identities": [
                {"region": "NA", "category": "A"},
                {"region": "EMEA", "category": "B"},
            ],
            "column_keys": ["default", "product_a"],
        },
    }


@pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")
class TestDropSourceCleanupCommands:
    """Explicit drop_source contributes a final-domain-cleanup drop command.

    The transformation records only the command; it keeps the source frame in
    the returned frames so later pipeline steps can still use it. Removal
    happens at the orchestrator-owned final cleanup boundary.
    """

    @staticmethod
    def _relation_frames() -> dict:
        return {
            "relations": pd.DataFrame(
                [
                    {"product": "p1", "market": "DE", "value": "x"},
                    {"product": "p1", "market": "JP", "value": "y"},
                ]
            )
        }

    def test_contract_xref_drop_source_marks_relation_for_cleanup(self) -> None:
        out = contract_xref(
            self._relation_frames(),
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="value",
            drop_source=True,
        )

        assert "relations" in out  # deferred: still available to later steps
        assert out["_meta"]["pipeline_cleanup"]["drop_frames"] == ["relations"]

    def test_expand_xref_drop_source_marks_matrix_for_cleanup(self) -> None:
        contracted = contract_xref(
            self._relation_frames(),
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="value",
        )
        out = expand_xref(
            contracted,
            matrix="matrix",
            output="relations_again",
            row_keys="product",
            column_key="market",
            value="value",
            drop_source=True,
        )

        assert "matrix" in out
        assert out["_meta"]["pipeline_cleanup"]["drop_frames"] == ["matrix"]

    def test_default_contributes_no_cleanup_command(self) -> None:
        out = contract_xref(
            self._relation_frames(),
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="value",
        )

        assert "pipeline_cleanup" not in out["_meta"]

    def test_drop_source_requires_distinct_output(self) -> None:
        with pytest.raises(ValueError, match="distinct output"):
            contract_xref(
                self._relation_frames(),
                relation="relations",
                output="relations",
                row_keys="product",
                column_key="market",
                value="value",
                drop_source=True,
            )


@pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")
class TestMinimalInverseIntent:
    """The persisted XRef contract is the minimal feature-local inverse intent.

    Retained fields all have concrete decision consumers: relation/matrix
    (intent discovery, column-role resolution, sparse defaults), row_keys
    (row-identity resolution), dense_axes intent (axis re-resolution), and
    the run-local column_keys / dense resolved Resolution facets (same-run
    contract reuse; stripped at the persistence boundary). Descriptive
    fields without a consumer (operation, column_key, value, drop_empty)
    are no longer written.
    """

    @staticmethod
    def _relation_frames() -> dict:
        return {
            "relations": pd.DataFrame(
                [
                    {"product": "p1", "market": "DE", "code": "x"},
                    {"product": "p2", "market": "JP", "code": "y"},
                ]
            )
        }

    def test_contract_writes_minimal_intent_payload(self) -> None:
        out = contract_xref(
            self._relation_frames(),
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="code",
        )

        assert out["_meta"]["xref_crosstable"]["relations"] == {
            "relation": "relations",
            "matrix": "matrix",
            "row_keys": ["product"],
            "column_keys": ["DE", "JP"],
        }
        assert list(out["_meta"]) == ["xref_crosstable"]

    def test_expand_writes_minimal_intent_payload(self) -> None:
        contracted = contract_xref(
            self._relation_frames(),
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="code",
        )
        out = expand_xref(
            {"matrix": contracted["matrix"]},
            matrix="matrix",
            output="relations_again",
            row_keys="product",
            column_key="market",
            value="code",
            drop_empty=True,
        )

        assert out["_meta"]["xref_crosstable"]["relations_again"] == {
            "matrix": "matrix",
            "relation": "relations_again",
            "row_keys": ["product"],
            "column_keys": ["DE", "JP"],
        }

    def test_persisted_intent_survives_boundary_without_resolution_facets(self) -> None:
        from spreadsheet_handling.pipeline.persistence_boundary import (
            project_meta_to_persistable_contract,
        )

        frames = {
            "resources": pd.DataFrame({"resource_key": ["r1"]}),
            "contexts": pd.DataFrame({"context_id": ["default"]}),
            "values": pd.DataFrame(
                [{"resource_key": "r1", "context_id": "default", "text": "Hello"}]
            ),
        }
        out = contract_xref(
            frames,
            relation="values",
            output="matrix",
            row_keys=["resource_key"],
            column_key="context_id",
            value="text",
            dense_axes={
                "rows_from": {"frame": "resources", "key": "resource_key"},
                "columns_from": {"frame": "contexts", "key": "context_id"},
            },
            name="resource_contexts",
        )

        persisted = project_meta_to_persistable_contract(out["_meta"])

        assert persisted["xref_crosstable"]["resource_contexts"] == {
            "relation": "values",
            "matrix": "matrix",
            "row_keys": ["resource_key"],
            "dense_axes": {
                "rows_from": {"frame": "resources", "key": "resource_key"},
                "columns_from": {"frame": "contexts", "key": "context_id"},
            },
        }

    def test_ambiguous_intent_fallback_fails_explicitly(self) -> None:
        frames = dict(self._relation_frames())
        frames["_meta"] = {
            "xref_crosstable": {
                "first": {"relation": "relations", "matrix": "matrix_a"},
                "second": {"relation": "relations", "matrix": "matrix_b"},
            }
        }

        with pytest.raises(ValueError, match="Ambiguous xref_crosstable metadata"):
            contract_xref(
                frames,
                relation="relations",
                output="matrix",
                row_keys="product",
                column_key="market",
                value="code",
                name="third",
            )

    def test_exact_config_id_wins_and_its_payload_is_consumed(self) -> None:
        # The two candidate entries carry observably different column_keys;
        # the produced matrix proves which entry the exact id selected.
        frames = dict(self._relation_frames())
        frames["_meta"] = {
            "xref_crosstable": {
                "first": {
                    "relation": "relations",
                    "matrix": "matrix_a",
                    "column_keys": ["DE", "JP", "US"],
                },
                "second": {
                    "relation": "relations",
                    "matrix": "matrix_b",
                    "column_keys": ["DE"],
                },
            }
        }

        out = contract_xref(
            frames,
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="code",
            name="first",
        )

        assert list(out["matrix"].columns) == ["product", "DE", "JP", "US"]

    def test_matrix_side_frame_fallback_ambiguity_fails(self) -> None:
        contracted = contract_xref(
            self._relation_frames(),
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="code",
        )
        meta = dict(contracted["_meta"])
        meta["xref_crosstable"] = {
            "first": {"relation": "rel_a", "matrix": "matrix"},
            "second": {"relation": "rel_b", "matrix": "matrix"},
        }

        with pytest.raises(ValueError, match="Ambiguous xref_crosstable metadata"):
            expand_xref(
                {"matrix": contracted["matrix"], "_meta": meta},
                matrix="matrix",
                output="relations_again",
                row_keys="product",
                column_key="market",
                value="code",
                name="third",
            )

    def test_no_generic_lifecycle_or_provenance_metadata_is_written(self) -> None:
        out = contract_xref(
            self._relation_frames(),
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="code",
            drop_source=True,
        )

        assert set(out["_meta"]) == {"xref_crosstable", "pipeline_cleanup"}


@pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")
class TestDropSourceLosslessGuards:
    """drop_source is rejected when the projection checkably loses values."""

    @staticmethod
    def _relation_frames() -> dict:
        return {
            "relations": pd.DataFrame(
                [
                    {"product": "p1", "market": "DE", "code": "x"},
                    {"product": "p1", "market": "JP", "code": "y"},
                ]
            )
        }

    def test_contract_drop_source_rejects_uncovered_relation_columns(self) -> None:
        with pytest.raises(ValueError, match="drop_source would lose relation column"):
            contract_xref(
                self._relation_frames(),
                relation="relations",
                output="matrix",
                row_keys="product",
                column_key="market",
                value="code",
                column_keys=["DE"],
                drop_source=True,
            )

    def test_contract_without_drop_source_allows_scoped_column_keys(self) -> None:
        out = contract_xref(
            self._relation_frames(),
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="code",
            column_keys=["DE"],
        )

        assert list(out["matrix"].columns) == ["product", "DE"]
        assert "relations" in out

    def test_contract_drop_source_allows_full_coverage(self) -> None:
        out = contract_xref(
            self._relation_frames(),
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="code",
            column_keys=["DE", "JP"],
            drop_source=True,
        )

        assert out["_meta"]["pipeline_cleanup"]["drop_frames"] == ["relations"]

    def test_expand_drop_source_rejects_unexpanded_value_columns(self) -> None:
        contracted = contract_xref(
            self._relation_frames(),
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="code",
        )

        with pytest.raises(ValueError, match="drop_source would lose matrix column"):
            expand_xref(
                {"matrix": contracted["matrix"]},
                matrix="matrix",
                output="relations_again",
                row_keys="product",
                value_columns=["DE"],
                column_key="market",
                value="code",
                drop_source=True,
            )


@pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")
class TestCarrierStableColumnIdentityContract:
    """XRef roundtrip column identities must be unique, non-empty strings.

    Spreadsheet carriers stringify headers, so numeric, missing,
    mixed-type, duplicate, or unhashable identities would silently change
    type, collide, or produce non-scalar cells on readback. Every identity
    source fails explicitly before any cleanup command is recorded.
    """

    @staticmethod
    def _relation(column_values: list) -> dict:
        return {
            "relations": pd.DataFrame(
                {
                    "product": [f"p{i}" for i in range(len(column_values))],
                    "market": column_values,
                    "code": ["x"] * len(column_values),
                }
            )
        }

    @staticmethod
    def _contract(frames: dict, **overrides):
        params = dict(
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="code",
        )
        params.update(overrides)
        return contract_xref(frames, **params)

    def test_none_column_identity_fails(self) -> None:
        with pytest.raises(ValueError, match="non-empty string column"):
            self._contract(self._relation(["DE", None]))

    def test_nan_column_identity_fails(self) -> None:
        import numpy as np

        with pytest.raises(ValueError, match="non-empty string column"):
            self._contract(self._relation(["DE", np.nan]))

    def test_pd_na_column_identity_fails(self) -> None:
        with pytest.raises(ValueError, match="non-empty string column"):
            self._contract(self._relation(["DE", pd.NA]))

    def test_numeric_column_identity_fails(self) -> None:
        with pytest.raises(ValueError, match="non-empty string column"):
            self._contract(self._relation([1, 2]))

    def test_numpy_numeric_scalar_identity_fails(self) -> None:
        import numpy as np

        with pytest.raises(ValueError, match="non-empty string column"):
            self._contract(self._relation([np.int64(1), np.int64(2)]))

    def test_mixed_numeric_and_string_identities_fail(self) -> None:
        # 1 and "1" are distinct in memory but collide as spreadsheet
        # headers; the numeric identity fails the contract outright.
        with pytest.raises(ValueError, match="non-empty string column"):
            self._contract(self._relation([1, "1"]))

    def test_unhashable_column_identity_fails(self) -> None:
        with pytest.raises(ValueError, match="non-empty string column"):
            self._contract(self._relation([["list"], "DE"]))

    def test_empty_string_column_identity_fails(self) -> None:
        with pytest.raises(ValueError, match="non-empty string column"):
            self._contract(self._relation(["DE", "  "]))

    def test_duplicate_explicit_column_keys_fail(self) -> None:
        with pytest.raises(ValueError, match="duplicate column identit"):
            self._contract(self._relation(["DE", "JP"]), column_keys=["DE", "DE", "JP"])

    def test_duplicate_metadata_derived_column_keys_fail(self) -> None:
        frames = self._relation(["DE", "JP"])
        frames["_meta"] = {
            "xref_crosstable": {
                "relations": {
                    "relation": "relations",
                    "matrix": "matrix",
                    "column_keys": ["DE", "DE", "JP"],
                }
            }
        }

        with pytest.raises(ValueError, match="duplicate column identit"):
            self._contract(frames)

    def test_duplicate_dense_derived_column_keys_fail(self) -> None:
        # Hand-authored stored snapshot with duplicates (the live axis-frame
        # path already rejects duplicates at the source frame).
        frames = self._relation(["DE", "JP"])

        with pytest.raises(ValueError, match="duplicate"):
            self._contract(
                frames,
                dense_axes={
                    "columns_from": {"frame": "absent_axis", "key": "id"},
                    "resolved": {"column_keys": ["DE", "DE", "JP"]},
                },
            )

    def test_duplicate_physical_matrix_labels_fail_expansion(self) -> None:
        matrix = pd.DataFrame(
            [["p1", "x", "y"]], columns=["product", "A", "A"]
        )

        with pytest.raises(ValueError, match="duplicate column label"):
            expand_xref(
                {"matrix": matrix},
                matrix="matrix",
                output="relations",
                row_keys="product",
                column_key="market",
                value="code",
            )

    def test_non_string_physical_matrix_labels_fail_expansion(self) -> None:
        matrix = pd.DataFrame([["p1", "x", "y"]], columns=["product", 1, 2])

        with pytest.raises(ValueError, match="non-empty string column"):
            expand_xref(
                {"matrix": matrix},
                matrix="matrix",
                output="relations",
                row_keys="product",
                column_key="market",
                value="code",
            )

    def test_valid_unique_string_identities_pass_with_drop_source(self) -> None:
        out = self._contract(self._relation(["DE", "JP"]), drop_source=True)

        assert list(out["matrix"].columns) == ["product", "DE", "JP"]
        assert out["_meta"]["pipeline_cleanup"]["drop_frames"] == ["relations"]


@pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")
class TestDropSourceUnrepresentedFields:
    """drop_source rejects relation fields the matrix does not represent."""

    @staticmethod
    def _frames_with_note() -> dict:
        return {
            "relations": pd.DataFrame(
                [{"product": "p1", "market": "DE", "code": "x", "note": "keep me"}]
            )
        }

    def test_additional_relation_field_with_drop_source_fails(self) -> None:
        with pytest.raises(ValueError, match="does not represent"):
            contract_xref(
                self._frames_with_note(),
                relation="relations",
                output="matrix",
                row_keys="product",
                column_key="market",
                value="code",
                drop_source=True,
            )

    def test_additional_relation_field_without_drop_source_is_allowed(self) -> None:
        out = contract_xref(
            self._frames_with_note(),
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="code",
        )

        assert list(out["matrix"].columns) == ["product", "DE"]
        assert "relations" in out
        assert "pipeline_cleanup" not in out["_meta"]

    def test_exactly_represented_relation_still_supports_drop_source(self) -> None:
        frames = {
            "relations": pd.DataFrame(
                [{"product": "p1", "market": "DE", "code": "x"}]
            )
        }

        out = contract_xref(
            frames,
            relation="relations",
            output="matrix",
            row_keys="product",
            column_key="market",
            value="code",
            drop_source=True,
        )

        assert out["_meta"]["pipeline_cleanup"]["drop_frames"] == ["relations"]
