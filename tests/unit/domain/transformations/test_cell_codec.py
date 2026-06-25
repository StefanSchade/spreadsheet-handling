from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.cell_codec import (
    decode_cell_values,
    encode_cell_values,
)


pytestmark = pytest.mark.ftr("FTR-CELL-CODEC")


def _position_codec_intent() -> dict[str, object]:
    return {
        "participating_columns": ["a", "b", "c"],
        "compact_column": "abc",
        "separator": " / ",
        "absent_value": "-",
    }


def test_position_based_contracts_configured_columns_into_compact_column() -> None:
    """Given expanded columns, when contracted, then they become one compact column."""
    # Given
    frames = {
        "expanded": pd.DataFrame([
            {"id": "row-1", "a": "A", "b": "B", "c": "C"},
            {"id": "row-2", "a": "A", "b": "", "c": "C"},
        ])
    }

    # When
    out = encode_cell_values(
        frames,
        source="expanded",
        output="compact",
        codec_intent=_position_codec_intent(),
    )

    # Then
    assert out["compact"].to_dict(orient="records") == [
        {"id": "row-1", "abc": "A / B / C"},
        {"id": "row-2", "abc": "A / - / C"},
    ]


def test_position_based_contract_preserves_non_participating_columns() -> None:
    """Given passthrough columns, when contracted, then they remain unchanged."""
    # Given
    frames = {
        "expanded": pd.DataFrame([
            {"id": "row-1", "note": "keep", "a": "A", "b": "B", "c": "C"},
        ])
    }

    # When
    out = encode_cell_values(
        frames,
        source="expanded",
        output="compact",
        codec_intent=_position_codec_intent(),
    )

    # Then
    assert out["compact"].to_dict(orient="records") == [
        {"id": "row-1", "note": "keep", "abc": "A / B / C"},
    ]


def test_position_based_contract_expands_compact_column_to_configured_columns() -> None:
    """Given a compact column, when decoded, then configured columns are restored."""
    # Given
    frames = {
        "compact": pd.DataFrame([
            {"id": "row-1", "abc": "A / B / C"},
            {"id": "row-2", "abc": "A / - / C"},
        ])
    }

    # When
    out = decode_cell_values(
        frames,
        source="compact",
        output="expanded",
        codec_intent=_position_codec_intent(),
    )

    # Then
    assert out["expanded"].to_dict(orient="records") == [
        {"id": "row-1", "a": "A", "b": "B", "c": "C"},
        {"id": "row-2", "a": "A", "b": "", "c": "C"},
    ]


def test_position_based_contract_requires_codec_intent_for_decoding() -> None:
    """Given no codec intent, when compact text contains separators, then no decode occurs."""
    # Given
    frames = {
        "compact": pd.DataFrame([
            {"id": "row-1", "abc": "A / B / C"},
        ])
    }

    # When / Then
    with pytest.raises(ValueError, match="codec intent"):
        decode_cell_values(
            frames,
            source="compact",
            output="expanded",
            value="abc",
        )


def test_position_based_contract_rejects_wrong_token_count() -> None:
    """Given too few tokens, when decoded, then the failure is hard."""
    # Given
    frames = {
        "compact": pd.DataFrame([
            {"id": "row-1", "abc": "A / B"},
        ])
    }

    # When / Then
    with pytest.raises(ValueError, match="token count"):
        decode_cell_values(
            frames,
            source="compact",
            output="expanded",
            codec_intent=_position_codec_intent(),
        )


def test_position_based_contract_rejects_helper_or_derived_participating_columns() -> None:
    """Given a helper column is selected, when contracted, then the failure is hard."""
    # Given
    frames = {
        "expanded": pd.DataFrame([
            {"id": "row-1", "a": "A", "b": "B", "c": "C"},
        ]),
        "_meta": {
            "derived": {
                "sheets": {
                    "expanded": {
                        "helper_columns": ["b"],
                    },
                },
            },
        },
    }

    # When / Then
    with pytest.raises(ValueError, match="helper|derived"):
        encode_cell_values(
            frames,
            source="expanded",
            output="compact",
            codec_intent=_position_codec_intent(),
        )
