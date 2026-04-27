from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.compact_multiaxis import (
    contract_compact_multiaxis,
    expand_compact_multiaxis,
)


pytestmark = pytest.mark.ftr("FTR-COMPACT-MULTIAXIS")


def _legend_meta() -> dict:
    return {
        "legend_blocks": {
            "status_codes": {
                "entries": [
                    {"token": "E", "label": "Editable", "group": "input"},
                    {"token": "E-R-K", "label": "Composite whole code", "group": "input"},
                    {"token": "S", "label": "System", "group": "system"},
                ],
            }
        }
    }


def test_expand_compact_multiaxis_produces_generic_long_form_with_legend_group() -> None:
    frames = {
        "product_matrix": pd.DataFrame({
            "feature_id": ["f1", "f2"],
            "P-001": ["E", "S"],
            "P-002": ["E-R-K", ""],
        }),
        "_meta": _legend_meta(),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="product_matrix",
        output="feature_product_codes",
        row_keys=["feature_id"],
        value_columns=["P-001", "P-002"],
        allowed_from_legend="status_codes",
        group="group",
    )

    assert out["feature_product_codes"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E", "group": "input"},
        {"feature_id": "f1", "column_key": "P-002", "code": "E-R-K", "group": "input"},
        {"feature_id": "f2", "column_key": "P-001", "code": "S", "group": "system"},
    ]
    assert "__compact_multiaxis_feature_product_codes_xref" not in out
    assert out["_meta"]["compact_multiaxis"]["feature_product_codes"]["drop_empty"] is True


def test_expand_compact_multiaxis_can_project_explicit_code_groups_without_legend() -> None:
    frames = {
        "product_matrix": pd.DataFrame({
            "feature_id": ["f1", "f2"],
            "P-001": ["E", "S"],
        })
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="product_matrix",
        output="feature_product_codes",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        allowed_codes=["E", "S"],
        code_groups={"E": "input", "S": "system"},
        group="group",
    )

    assert out["feature_product_codes"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E", "group": "input"},
        {"feature_id": "f2", "column_key": "P-001", "code": "S", "group": "system"},
    ]
    assert out["_meta"]["compact_multiaxis"]["feature_product_codes"]["code_groups"] == {
        "E": "input",
        "S": "system",
    }


def test_conflicting_legend_and_explicit_code_groups_are_rejected() -> None:
    frames = {
        "product_matrix": pd.DataFrame({
            "feature_id": ["f1"],
            "P-001": ["E"],
        }),
        "_meta": _legend_meta(),
    }

    with pytest.raises(ValueError, match="Conflicting group value"):
        expand_compact_multiaxis(
            frames,
            matrix="product_matrix",
            output="feature_product_codes",
            row_keys=["feature_id"],
            value_columns=["P-001"],
            allowed_from_legend="status_codes",
            code_groups={"E": "other"},
            group="group",
        )


def test_compact_multiaxis_whole_cell_roundtrip_can_preserve_empty_cells_when_configured() -> None:
    frames = {
        "product_matrix": pd.DataFrame({
            "feature_id": ["f1", "f2"],
            "P-001": ["E", "S"],
            "P-002": ["E-R-K", ""],
        }),
        "_meta": _legend_meta(),
    }
    expanded = expand_compact_multiaxis(
        frames,
        matrix="product_matrix",
        output="feature_product_codes",
        row_keys=["feature_id"],
        value_columns=["P-001", "P-002"],
        allowed_from_legend="status_codes",
        drop_empty=False,
    )

    out = contract_compact_multiaxis(
        expanded,
        relation="feature_product_codes",
        output="product_matrix_roundtrip",
        row_keys=["feature_id"],
        allowed_from_legend="status_codes",
    )

    assert out["product_matrix_roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E", "P-002": "E-R-K"},
        {"feature_id": "f2", "P-001": "S", "P-002": ""},
    ]


def test_compact_multiaxis_sparse_default_keeps_sparse_relations_sparse() -> None:
    frames = {
        "matrix": pd.DataFrame({
            "feature_id": ["f1", "f2"],
            "P-001": ["E", ""],
        }),
        "_meta": _legend_meta(),
    }

    expanded = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        allowed_from_legend="status_codes",
    )
    out = contract_compact_multiaxis(
        expanded,
        relation="explicit",
        output="roundtrip",
        row_keys=["feature_id"],
        allowed_from_legend="status_codes",
    )

    assert out["explicit"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E"},
    ]
    assert out["roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E"},
    ]


def test_split_token_multiaxis_roundtrip_uses_canonical_order() -> None:
    frames = {
        "matrix": pd.DataFrame({
            "feature_id": ["f1"],
            "P-001": ["K-E"],
        })
    }

    expanded = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        mode="split_tokens",
        delimiter="-",
        allowed_tokens=["E", "K"],
    )
    out = contract_compact_multiaxis(
        expanded,
        relation="explicit",
        output="roundtrip",
        row_keys=["feature_id"],
        mode="split_tokens",
        delimiter="-",
        allowed_tokens=["E", "K"],
        canonical_order=["E", "K"],
    )

    assert expanded["explicit"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "K"},
        {"feature_id": "f1", "column_key": "P-001", "code": "E"},
    ]
    assert out["roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E-K"},
    ]


def test_expand_rejects_dense_axes_until_explicitly_implemented() -> None:
    frames = {
        "matrix": pd.DataFrame({
            "feature_id": ["f1"],
            "P-001": ["E"],
        })
    }

    with pytest.raises(NotImplementedError, match="dense_axes"):
        expand_compact_multiaxis(
            frames,
            matrix="matrix",
            output="explicit",
            row_keys=["feature_id"],
            dense_axes={
                "rows_from": {"frame": "Products", "key": "product_id"},
            },
        )


def test_contract_rejects_dense_axes_until_explicitly_implemented() -> None:
    frames = {
        "explicit": pd.DataFrame([
            {"feature_id": "f1", "column_key": "P-001", "code": "E"},
        ])
    }

    with pytest.raises(NotImplementedError, match="dense_axes"):
        contract_compact_multiaxis(
            frames,
            relation="explicit",
            output="matrix",
            row_keys=["feature_id"],
            dense_axes={
                "rows_from": {"frame": "Products", "key": "product_id"},
                "columns_from": {"frame": "Markets", "key": "market_id"},
            },
        )
