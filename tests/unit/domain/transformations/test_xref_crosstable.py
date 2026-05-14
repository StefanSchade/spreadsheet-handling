from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.xref_crosstable import (
    contract_xref,
    expand_xref,
)


pytestmark = pytest.mark.ftr("FTR-XREF-CROSSTABLE")
DENSE_FTR = pytest.mark.ftr("FTR-XREF-DENSE-AXES-P4A2")


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

    with pytest.raises(ValueError, match="tuple labels"):
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
