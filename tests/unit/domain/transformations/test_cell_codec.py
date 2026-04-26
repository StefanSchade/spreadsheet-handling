from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.cell_codec import (
    ParsedCellValue,
    decode_cell_values,
    encode_cell_values,
    parse_cell_value,
    serialize_cell_value,
)
from spreadsheet_handling.domain.transformations.xref_crosstable import (
    contract_xref,
    expand_xref,
)


pytestmark = pytest.mark.ftr("FTR-CELL-CODEC")


def test_whole_cell_code_keeps_delimited_looking_code_intact() -> None:
    parsed = parse_cell_value(
        "E-R-K",
        mode="whole_cell_code",
        allowed_codes=["S", "E-R-K"],
    )

    assert parsed == ParsedCellValue(mode="whole_cell_code", values=("E-R-K",))
    assert serialize_cell_value(parsed, mode="whole_cell_code", allowed_codes=["S", "E-R-K"]) == "E-R-K"


def test_split_tokens_requires_explicit_mode_and_serializes_in_canonical_order() -> None:
    parsed = parse_cell_value(
        "K-E-R",
        mode="split_tokens",
        delimiter="-",
        allowed_tokens=["E", "R", "K"],
    )

    assert parsed.values == ("K", "E", "R")
    assert (
        serialize_cell_value(
            parsed,
            mode="split_tokens",
            delimiter="-",
            allowed_tokens=["E", "R", "K"],
            canonical_order=["E", "R", "K"],
        )
        == "E-R-K"
    )


def test_serialize_split_tokens_expects_structured_values_not_compact_cell_text() -> None:
    assert (
        serialize_cell_value(
            ["K", "E"],
            mode="split_tokens",
            delimiter="-",
            allowed_tokens=["K", "E"],
        )
        == "K-E"
    )

    with pytest.raises(ValueError, match="Invalid cell token"):
        serialize_cell_value(
            "K-E",
            mode="split_tokens",
            delimiter="-",
            allowed_tokens=["K", "E"],
        )


def test_invalid_whole_cell_code_is_rejected_when_allowed_codes_are_configured() -> None:
    with pytest.raises(ValueError, match="Invalid cell code"):
        parse_cell_value("X", mode="whole_cell_code", allowed_codes=["E", "S"])


def test_codec_can_source_allowed_values_from_legend_block() -> None:
    meta = {
        "legend_blocks": {
            "status_codes": {
                "entries": [
                    {"token": "E", "label": "Editable"},
                    {"token": "E-R-K", "label": "Capital-path recalculation"},
                ],
            }
        }
    }

    assert (
        parse_cell_value(
            "E-R-K",
            mode="whole_cell_code",
            allowed_from_legend="status_codes",
            meta=meta,
        ).values
        == ("E-R-K",)
    )

    with pytest.raises(ValueError, match="Invalid cell code"):
        parse_cell_value(
            "X",
            mode="whole_cell_code",
            allowed_from_legend="status_codes",
            meta=meta,
        )


def test_duplicate_explicit_and_legend_allowed_values_are_config_error() -> None:
    meta = {
        "legend_blocks": {
            "status_codes": {
                "entries": [
                    {"token": "E", "label": "Editable"},
                ],
            }
        }
    }

    with pytest.raises(ValueError, match="Allowed value set contains duplicate"):
        parse_cell_value(
            "E",
            mode="whole_cell_code",
            allowed_codes=["E"],
            allowed_from_legend="status_codes",
            meta=meta,
        )


def test_decode_cell_values_emits_one_code_row_for_whole_cell_codes() -> None:
    frames = {
        "long": pd.DataFrame([
            {"feature_id": "f1", "column_key": "P-001", "value": "E-R-K"},
            {"feature_id": "f2", "column_key": "P-001", "value": ""},
        ])
    }

    out = decode_cell_values(
        frames,
        source="long",
        output="decoded",
        passthrough_columns=["feature_id", "column_key"],
        allowed_codes=["E-R-K"],
    )

    assert out["decoded"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E-R-K"},
    ]
    assert out["_meta"]["cell_codecs"]["decoded"]["mode"] == "whole_cell_code"


def test_decode_cell_values_can_split_tokens_and_preserve_empty_rows_when_requested() -> None:
    frames = {
        "long": pd.DataFrame([
            {"feature_id": "f1", "column_key": "P-001", "value": "K-E"},
            {"feature_id": "f2", "column_key": "P-001", "value": ""},
        ])
    }

    out = decode_cell_values(
        frames,
        source="long",
        output="decoded",
        passthrough_columns=["feature_id", "column_key"],
        drop_empty=False,
        mode="split_tokens",
        delimiter="-",
        allowed_tokens=["E", "K"],
    )

    assert out["decoded"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "K"},
        {"feature_id": "f1", "column_key": "P-001", "code": "E"},
        {"feature_id": "f2", "column_key": "P-001", "code": ""},
    ]


def test_encode_cell_values_groups_tokens_into_canonical_cell_values() -> None:
    frames = {
        "decoded": pd.DataFrame([
            {"feature_id": "f1", "column_key": "P-001", "code": "K"},
            {"feature_id": "f1", "column_key": "P-001", "code": "E"},
            {"feature_id": "f2", "column_key": "P-001", "code": ""},
        ])
    }

    out = encode_cell_values(
        frames,
        source="decoded",
        output="encoded",
        group_by=["feature_id", "column_key"],
        mode="split_tokens",
        delimiter="-",
        allowed_tokens=["E", "K"],
        canonical_order=["E", "K"],
    )

    assert out["encoded"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "value": "E-K"},
        {"feature_id": "f2", "column_key": "P-001", "value": ""},
    ]


def test_sparse_decode_default_can_drop_empty_only_xref_groups() -> None:
    frames = {
        "matrix": pd.DataFrame({
            "feature_id": ["f1", "f2"],
            "P-001": ["E", ""],
        })
    }
    expanded = expand_xref(
        frames,
        matrix="matrix",
        output="long",
        row_keys=["feature_id"],
        value_columns=["P-001"],
    )
    decoded = decode_cell_values(
        expanded,
        source="long",
        output="decoded",
        passthrough_columns=["feature_id", "column_key"],
        allowed_codes=["E"],
    )
    encoded = encode_cell_values(
        decoded,
        source="decoded",
        output="encoded",
        group_by=["feature_id", "column_key"],
        allowed_codes=["E"],
    )
    roundtrip = contract_xref(
        encoded,
        relation="encoded",
        output="roundtrip",
        row_keys=["feature_id"],
        column_keys=["P-001"],
    )

    assert roundtrip["roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E"},
    ]


def test_drop_empty_false_preserves_empty_xref_groups_for_lossless_roundtrip() -> None:
    frames = {
        "matrix": pd.DataFrame({
            "feature_id": ["f1", "f2"],
            "P-001": ["E", ""],
        })
    }
    expanded = expand_xref(
        frames,
        matrix="matrix",
        output="long",
        row_keys=["feature_id"],
        value_columns=["P-001"],
    )
    decoded = decode_cell_values(
        expanded,
        source="long",
        output="decoded",
        passthrough_columns=["feature_id", "column_key"],
        drop_empty=False,
        allowed_codes=["E"],
    )
    encoded = encode_cell_values(
        decoded,
        source="decoded",
        output="encoded",
        group_by=["feature_id", "column_key"],
        allowed_codes=["E"],
    )
    roundtrip = contract_xref(
        encoded,
        relation="encoded",
        output="roundtrip",
        row_keys=["feature_id"],
        column_keys=["P-001"],
    )

    assert roundtrip["roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E"},
        {"feature_id": "f2", "P-001": ""},
    ]


def test_encode_cell_values_rejects_multiple_whole_codes_per_group() -> None:
    frames = {
        "decoded": pd.DataFrame([
            {"feature_id": "f1", "column_key": "P-001", "code": "E"},
            {"feature_id": "f1", "column_key": "P-001", "code": "S"},
        ])
    }

    with pytest.raises(ValueError, match="exactly one code"):
        encode_cell_values(
            frames,
            source="decoded",
            output="encoded",
            group_by=["feature_id", "column_key"],
            allowed_codes=["E", "S"],
        )
