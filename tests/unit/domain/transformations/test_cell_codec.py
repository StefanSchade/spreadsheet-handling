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


@pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")
class TestNoPersistedCodecMetadata:
    """Cell Codec intent lives in explicit configuration only.

    _meta.cell_codecs had no runtime reader anywhere; the producer was
    removed under the projection-family rule. Legacy payloads remain
    tolerated pass-through sediment.
    """

    def test_position_encode_and_decode_write_no_codec_metadata(self) -> None:
        frames = {
            "expanded": pd.DataFrame([{"id": "r1", "a": "A", "b": "B", "c": "C"}]),
            "_meta": {},
        }

        encoded = encode_cell_values(
            frames,
            source="expanded",
            output="compact",
            codec_intent=_position_codec_intent(),
        )
        decoded = decode_cell_values(
            {"compact": encoded["compact"], "_meta": dict(encoded.get("_meta") or {})},
            source="compact",
            output="expanded_again",
            codec_intent=_position_codec_intent(),
        )

        assert "cell_codecs" not in (encoded.get("_meta") or {})
        assert "cell_codecs" not in (decoded.get("_meta") or {})

    def test_legacy_paths_write_no_codec_metadata(self) -> None:
        frames = {
            "rows": pd.DataFrame(
                [
                    {"key": "k1", "code": "A"},
                    {"key": "k1", "code": "B"},
                ]
            ),
        }

        encoded = encode_cell_values(
            frames,
            source="rows",
            output="cells",
            group_by="key",
            mode="split_tokens",
            delimiter="-",
        )
        decoded = decode_cell_values(
            {"cells": encoded["cells"]},
            source="cells",
            output="rows_again",
            mode="split_tokens",
            delimiter="-",
        )

        assert "cell_codecs" not in (encoded.get("_meta") or {})
        assert "cell_codecs" not in (decoded.get("_meta") or {})
        assert sorted(decoded["rows_again"]["code"].tolist()) == ["A", "B"]

    def test_inputs_and_metadata_are_not_mutated(self) -> None:
        import copy

        meta = {"legend_blocks": {"codes": {"entries": [{"token": "A", "label": "a"}]}}}
        source = pd.DataFrame([{"id": "r1", "a": "A", "b": "B", "c": "C"}])
        frames = {"expanded": source, "_meta": meta}
        meta_snapshot = copy.deepcopy(meta)
        source_snapshot = source.copy()

        encode_cell_values(
            frames,
            source="expanded",
            output="compact",
            codec_intent=_position_codec_intent(),
        )

        assert frames["_meta"] == meta_snapshot
        pd.testing.assert_frame_equal(frames["expanded"], source_snapshot)

    def test_decode_without_explicit_intent_fails_with_no_metadata_fallback(self) -> None:
        # There is no metadata lookup: legacy payloads must not resurrect
        # decoding configuration.
        frames = {
            "compact": pd.DataFrame([{"id": "r1", "abc": "A / B / C"}]),
            "_meta": {
                "cell_codecs": {
                    "compact": {
                        "participating_columns": ["a", "b", "c"],
                        "compact_column": "abc",
                        "separator": " / ",
                        "absent_value": "-",
                    }
                }
            },
        }

        with pytest.raises(ValueError, match="codec intent is required"):
            decode_cell_values(frames, source="compact", output="expanded")


@pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")
class TestPositionIntentDeclarationGuards:
    """Malformed or ambiguous codec intent fails explicitly."""

    @staticmethod
    def _frames() -> dict:
        return {
            "expanded": pd.DataFrame([{"id": "r1", "a": "A", "b": "B", "c": "C"}])
        }

    def _encode(self, frames: dict, **intent_overrides: object):
        intent = _position_codec_intent()
        intent.update(intent_overrides)
        return encode_cell_values(
            frames,
            source="expanded",
            output="compact",
            codec_intent=intent,
        )

    def test_duplicate_participating_columns_fail(self) -> None:
        with pytest.raises(ValueError, match="duplicate field"):
            self._encode(self._frames(), participating_columns=["a", "a", "b"])

    def test_missing_participating_column_fails(self) -> None:
        with pytest.raises(KeyError, match="missing columns"):
            self._encode(self._frames(), participating_columns=["a", "nope"])

    def test_compact_column_must_not_be_participating(self) -> None:
        with pytest.raises(ValueError, match="must not also be"):
            self._encode(self._frames(), compact_column="a")

    def test_compact_column_collision_with_passthrough_fails(self) -> None:
        with pytest.raises(ValueError, match="collides"):
            self._encode(self._frames(), compact_column="id")

    def test_absent_value_containing_separator_fails(self) -> None:
        with pytest.raises(ValueError, match="must not contain the"):
            self._encode(self._frames(), separator="/", absent_value="-/-")

    def test_duplicate_physical_source_labels_fail(self) -> None:
        frames = {
            "expanded": pd.DataFrame(
                [["r1", "A", "B", "C"]], columns=["a", "a", "b", "c"]
            )
        }

        with pytest.raises(ValueError, match="duplicate physical column label"):
            self._encode(frames)

    def test_decode_overlap_with_existing_columns_fails(self) -> None:
        frames = {
            "compact": pd.DataFrame([{"id": "r1", "a": "already", "abc": "A / B / C"}])
        }

        with pytest.raises(ValueError, match="already"):
            decode_cell_values(
                frames,
                source="compact",
                output="expanded",
                codec_intent=_position_codec_intent(),
            )


@pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")
class TestStringOrientedValueContract:
    """Cell Codec is string-oriented; typed values fail explicitly."""

    @staticmethod
    def _encode(rows: list[dict]) -> dict:
        return encode_cell_values(
            {"expanded": pd.DataFrame(rows)},
            source="expanded",
            output="compact",
            codec_intent=_position_codec_intent(),
        )

    def test_numeric_participating_value_fails(self) -> None:
        with pytest.raises(ValueError, match="string-oriented"):
            self._encode([{"id": "r1", "a": 1, "b": "B", "c": "C"}])

    def test_boolean_participating_value_fails(self) -> None:
        with pytest.raises(ValueError, match="string-oriented"):
            self._encode([{"id": "r1", "a": True, "b": "B", "c": "C"}])

    def test_date_participating_value_fails(self) -> None:
        with pytest.raises(ValueError, match="string-oriented"):
            self._encode(
                [{"id": "r1", "a": pd.Timestamp("2026-01-01"), "b": "B", "c": "C"}]
            )

    def test_mixed_typed_and_string_values_fail_on_the_typed_value(self) -> None:
        # 1 and "1" stringify identically; the typed value fails outright so
        # the ambiguity cannot arise.
        with pytest.raises(ValueError, match="string-oriented"):
            self._encode(
                [
                    {"id": "r1", "a": "1", "b": "B", "c": "C"},
                    {"id": "r2", "a": 1, "b": "B", "c": "C"},
                ]
            )

    def test_empty_string_and_missing_both_encode_as_absent(self) -> None:
        out = self._encode(
            [
                {"id": "r1", "a": "", "b": "B", "c": "C"},
                {"id": "r2", "a": None, "b": "B", "c": "C"},
            ]
        )

        assert out["compact"]["abc"].tolist() == ["- / B / C", "- / B / C"]

    def test_absent_decodes_to_empty_string_not_null(self) -> None:
        out = decode_cell_values(
            {"compact": pd.DataFrame([{"id": "r1", "abc": "- / B / C"}])},
            source="compact",
            output="expanded",
            codec_intent=_position_codec_intent(),
        )

        record = out["expanded"].to_dict(orient="records")[0]
        assert record["a"] == ""
        assert record["b"] == "B"

    def test_separator_inside_value_fails_encoding(self) -> None:
        # No escaping or quoting exists; ambiguous encodes are rejected.
        with pytest.raises(ValueError, match="contains codec separator"):
            self._encode([{"id": "r1", "a": "A / X", "b": "B", "c": "C"}])


@pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")
class TestLegacyCodeRowContract:
    """Wrapper-consumed historical path: characterized, not redesigned."""

    def test_split_tokens_serialization_rejects_delimiter_in_token(self) -> None:
        from spreadsheet_handling.domain.transformations.cell_codec import (
            serialize_cell_value,
        )

        with pytest.raises(ValueError, match="contain the delimiter"):
            serialize_cell_value(
                ["A-B", "C"], mode="split_tokens", delimiter="-"
            )

    def test_whole_cell_code_may_contain_delimiter_characters(self) -> None:
        from spreadsheet_handling.domain.transformations.cell_codec import (
            serialize_cell_value,
        )

        assert serialize_cell_value(["E-R-K"], mode="whole_cell_code") == "E-R-K"

    def test_legacy_encode_stringifies_typed_codes(self) -> None:
        # Characterization of wrapper-era behavior: the historical code-row
        # path stringifies values (str substrate); tightening is deferred to
        # the compact_multiaxis composite slice.
        out = encode_cell_values(
            {"rows": pd.DataFrame([{"key": "k1", "code": 7}])},
            source="rows",
            output="cells",
            group_by="key",
            mode="whole_cell_code",
        )

        assert out["cells"]["value"].tolist() == ["7"]

    def test_legacy_duplicate_group_by_fails(self) -> None:
        with pytest.raises(ValueError, match="duplicate field"):
            encode_cell_values(
                {"rows": pd.DataFrame([{"key": "k1", "code": "A"}])},
                source="rows",
                output="cells",
                group_by=["key", "key"],
                mode="whole_cell_code",
            )

    def test_legacy_duplicate_physical_labels_fail(self) -> None:
        frames = {
            "rows": pd.DataFrame([["k1", "A", "B"]], columns=["key", "code", "code"])
        }

        with pytest.raises(ValueError, match="duplicate physical column label"):
            encode_cell_values(
                frames,
                source="rows",
                output="cells",
                group_by="key",
                mode="whole_cell_code",
            )
