from __future__ import annotations

import copy

import numpy as np
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
        "separator": "/",
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
        {"id": "row-1", "abc": "A/B/C"},
        {"id": "row-2", "abc": "A/-/C"},
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
        {"id": "row-1", "note": "keep", "abc": "A/B/C"},
    ]


def test_position_based_contract_expands_compact_column_to_configured_columns() -> None:
    """Given a compact column, when decoded, then configured columns are restored."""
    # Given
    frames = {
        "compact": pd.DataFrame([
            {"id": "row-1", "abc": "A/B/C"},
            {"id": "row-2", "abc": "A/-/C"},
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
            {"id": "row-1", "abc": "A/B/C"},
        ])
    }

    # When/Then
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
            {"id": "row-1", "abc": "A/B"},
        ])
    }

    # When/Then
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

    # When/Then
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
            "compact": pd.DataFrame([{"id": "r1", "abc": "A/B/C"}]),
            "_meta": {
                "cell_codecs": {
                    "compact": {
                        "participating_columns": ["a", "b", "c"],
                        "compact_column": "abc",
                        "separator": "/",
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
        # one-char separator "/" is contained in absent_value "-/-": rejected.
        with pytest.raises(ValueError, match="must not contain the separator"):
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
            "compact": pd.DataFrame([{"id": "r1", "a": "already", "abc": "A/B/C"}])
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

        assert out["compact"]["abc"].tolist() == ["-/B/C", "-/B/C"]

    def test_absent_decodes_to_empty_string_not_null(self) -> None:
        out = decode_cell_values(
            {"compact": pd.DataFrame([{"id": "r1", "abc": "-/B/C"}])},
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
            self._encode([{"id": "r1", "a": "A/X", "b": "B", "c": "C"}])


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


def _object_columns(labels: list) -> pd.Index:
    """Build an object-dtype column Index preserving exotic label objects."""
    arr = np.empty(len(labels), dtype=object)
    arr[:] = labels
    return pd.Index(arr, dtype=object)


class TestSharedPhysicalLabelBoundary:
    """B1: all four Cell Codec paths reject unaddressable physical labels.

    Physical labels must be non-missing, hashable, uniquely and
    deterministically comparable, and scalar-addressable -- but not
    string-only (unique numeric labels stay valid). No physical label reaches
    pandas membership/selection/grouping/row-indexing before the shared
    boundary runs.
    """

    @staticmethod
    def _assert_no_output_or_metadata(frames: dict, before_meta: object) -> None:
        assert "out" not in frames
        assert frames.get("_meta") == before_meta

    def test_position_encode_duplicate_strings_rejected(self) -> None:
        frames = {"s": pd.DataFrame([["x", "y"]], columns=_object_columns(["a", "a"]))}
        with pytest.raises(ValueError, match="duplicate physical column label"):
            encode_cell_values(
                frames,
                source="s",
                output="out",
                codec_intent={
                    "participating_columns": ["a"],
                    "compact_column": "p",
                    "separator": "|",
                    "absent_value": "-",
                },
            )
        assert "out" not in frames

    def test_position_encode_duplicate_nan_rejected(self) -> None:
        frames = {"s": pd.DataFrame([["x", "y"]], columns=_object_columns([np.nan, np.nan]))}
        with pytest.raises(ValueError, match="missing-like physical column label"):
            encode_cell_values(
                frames,
                source="s",
                output="out",
                codec_intent={
                    "participating_columns": ["a"],
                    "compact_column": "p",
                    "separator": "|",
                    "absent_value": "-",
                },
            )
        assert "out" not in frames

    def test_position_encode_duplicate_pd_na_rejected(self) -> None:
        frames = {"s": pd.DataFrame([["x", "y"]], columns=_object_columns([pd.NA, pd.NA]))}
        with pytest.raises(ValueError, match="missing-like physical column label"):
            encode_cell_values(
                frames,
                source="s",
                output="out",
                codec_intent={
                    "participating_columns": ["a"],
                    "compact_column": "p",
                    "separator": "|",
                    "absent_value": "-",
                },
            )
        assert "out" not in frames

    def test_position_encode_selected_list_label_rejected(self) -> None:
        frames = {"s": pd.DataFrame([["x", "y"]], columns=_object_columns(["a", [1, 2]]))}
        with pytest.raises(ValueError, match="unhashable physical column label"):
            encode_cell_values(
                frames,
                source="s",
                output="out",
                codec_intent={
                    "participating_columns": ["a"],
                    "compact_column": "p",
                    "separator": "|",
                    "absent_value": "-",
                },
            )
        assert "out" not in frames

    def test_position_encode_selected_numpy_array_label_rejected(self) -> None:
        frames = {
            "s": pd.DataFrame([["x", "y"]], columns=_object_columns(["a", np.array([1, 2])]))
        }
        with pytest.raises(ValueError, match="ambiguous equality"):
            encode_cell_values(
                frames,
                source="s",
                output="out",
                codec_intent={
                    "participating_columns": ["a"],
                    "compact_column": "p",
                    "separator": "|",
                    "absent_value": "-",
                },
            )
        assert "out" not in frames

    def test_position_encode_unique_numeric_labels_supported(self) -> None:
        # Physical labels are not string-only: a unique numeric label is
        # scalar-addressable and remains valid.
        frames = {"s": pd.DataFrame([["A", "B"]], columns=_object_columns(["a", 7]))}
        out = encode_cell_values(
            frames,
            source="s",
            output="out",
            codec_intent={
                "participating_columns": ["a"],
                "compact_column": "p",
                "separator": "|",
                "absent_value": "-",
            },
        )
        # numeric label 7 is a passthrough column preserved on the output
        assert 7 in out["out"].columns

    def test_position_decode_selected_list_label_rejected(self) -> None:
        frames = {"s": pd.DataFrame([["x", "y"]], columns=_object_columns(["p", [1, 2]]))}
        with pytest.raises(ValueError, match="unhashable physical column label"):
            decode_cell_values(
                frames,
                source="s",
                output="out",
                codec_intent={
                    "participating_columns": ["a"],
                    "compact_column": "p",
                    "separator": "|",
                    "absent_value": "-",
                },
            )
        assert "out" not in frames

    def test_historical_encode_duplicate_nan_corruption_closed(self) -> None:
        # Review 001 corruption case: two physical NaN labels with both
        # group_by and code addressing NaN previously made row[NaN] a Series
        # and serialized its string representation as the cell. Now rejected.
        frames = {
            "s": pd.DataFrame(
                [["G", "x", "y"]], columns=_object_columns(["g", np.nan, np.nan])
            ),
            "_meta": {"sentinel": {"keep": ["unchanged"]}},
        }
        before_frame = frames["s"].copy()
        before_meta = copy.deepcopy(frames["_meta"])

        with pytest.raises(ValueError, match="missing-like physical column label"):
            encode_cell_values(
                frames,
                source="s",
                output="out",
                group_by="g",
                code=np.nan,
                value="v",
                mode="whole_cell_code",
            )

        assert "out" not in frames
        assert "cell_codecs" not in frames["_meta"]
        assert frames["_meta"] == before_meta
        assert frames["s"].equals(before_frame)
        # The column labels are still the two NaN objects (no Series serialized).
        assert frames["s"].shape == before_frame.shape

    def test_historical_decode_selected_list_label_rejected(self) -> None:
        frames = {
            "s": pd.DataFrame([["x", "y"]], columns=_object_columns(["value", [1, 2]]))
        }
        with pytest.raises(ValueError, match="unhashable physical column label"):
            decode_cell_values(
                frames,
                source="s",
                output="out",
                mode="whole_cell_code",
            )
        assert "out" not in frames

    def test_tuple_columns_rejected_by_flat_frame_guard(self) -> None:
        # Tuple/MultiIndex operation surfaces are deliberately rejected by the
        # flat-frame guard (not promised by this slice), independently of the
        # scalar-addressable physical-label boundary.
        frames = {"s": pd.DataFrame([["x", "y"]], columns=[("a", "b"), ("c", "d")])}
        with pytest.raises(ValueError, match="MultiIndex/tuple columns"):
            encode_cell_values(
                frames,
                source="s",
                output="out",
                codec_intent={
                    "participating_columns": [("a", "b")],
                    "compact_column": "p",
                    "separator": "|",
                    "absent_value": "-",
                },
            )
        assert "out" not in frames


class TestPositionGrammarSoundness:
    """R002-B2: one-character separator makes every encode decodable.

    The no-escaping grammar requires `codec_intent.separator` to be exactly one
    Unicode character, so a separator occurrence cannot be formed across a
    token/marker boundary.
    """

    @staticmethod
    def _intent(separator: str, absent_value: str) -> dict:
        return {
            "participating_columns": ["a", "b", "c"],
            "compact_column": "packed",
            "separator": separator,
            "absent_value": absent_value,
        }

    def test_multi_character_separator_rejected(self) -> None:
        with pytest.raises(ValueError, match="exactly one character"):
            encode_cell_values(
                {"s": pd.DataFrame([{"a": "A", "b": "B", "c": "C"}])},
                source="s",
                output="out",
                codec_intent=self._intent(separator="--", absent_value="-"),
            )

    def test_review_002_cross_boundary_counterexample_rejected(self) -> None:
        # separator="--", absent_value="~", values ["A-","B","C"] previously
        # encoded to "A---B--C" and decoded to ["A","-B","C"]. The token "A-"
        # ends in a separator prefix; the multi-character separator is now
        # rejected at declaration validation.
        with pytest.raises(ValueError, match="exactly one character"):
            encode_cell_values(
                {"s": pd.DataFrame([{"a": "A-", "b": "B", "c": "C"}])},
                source="s",
                output="out",
                codec_intent=self._intent(separator="--", absent_value="~"),
            )

    def test_multi_character_absent_prefix_counterexample_rejected(self) -> None:
        # separator="--", absent_value="x-" also formed a cross-boundary
        # separator; rejected because the separator is multi-character.
        with pytest.raises(ValueError, match="exactly one character"):
            encode_cell_values(
                {"s": pd.DataFrame([{"a": "A", "b": "", "c": "B"}])},
                source="s",
                output="out",
                codec_intent=self._intent(separator="--", absent_value="x-"),
            )

    def test_review_001_counterexample_rejected_as_multi_char(self) -> None:
        # separator="--", absent_value="-", values ["A","","B"].
        with pytest.raises(ValueError, match="exactly one character"):
            encode_cell_values(
                {"s": pd.DataFrame([{"a": "A", "b": "", "c": "B"}])},
                source="s",
                output="out",
                codec_intent=self._intent(separator="--", absent_value="-"),
            )

    def test_absent_marker_containing_one_char_separator_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not contain the separator"):
            encode_cell_values(
                {"s": pd.DataFrame([{"a": "A", "b": "B", "c": "C"}])},
                source="s",
                output="out",
                codec_intent=self._intent(separator="/", absent_value="-/-"),
            )

    def test_separator_equal_absent_rejected(self) -> None:
        with pytest.raises(ValueError, match="must differ"):
            encode_cell_values(
                {"s": pd.DataFrame([{"a": "A", "b": "B", "c": "C"}])},
                source="s",
                output="out",
                codec_intent=self._intent(separator="|", absent_value="|"),
            )

    @pytest.mark.parametrize("separator", ["|", "/", ";"])
    def test_valid_one_character_separators_roundtrip(self, separator: str) -> None:
        intent = self._intent(separator=separator, absent_value="-")
        frames = {
            "s": pd.DataFrame(
                [
                    {"a": "A", "b": "", "c": "B"},
                    {"a": "003", "b": "x", "c": None},
                    {"a": "pre-post", "b": "1", "c": "2"},
                ]
            )
        }
        encoded = encode_cell_values(frames, source="s", output="packed_f", codec_intent=intent)
        decoded = decode_cell_values(encoded, source="packed_f", output="round", codec_intent=intent)
        assert decoded["round"][["a", "b", "c"]].to_dict(orient="records") == [
            {"a": "A", "b": "", "c": "B"},
            {"a": "003", "b": "x", "c": ""},
            {"a": "pre-post", "b": "1", "c": "2"},
        ]

    def test_valid_encode_followed_by_identical_decode(self) -> None:
        intent = self._intent(separator="|", absent_value="-")
        frames = {"s": pd.DataFrame([{"a": "A", "b": "", "c": "B"}])}
        encoded = encode_cell_values(frames, source="s", output="packed_f", codec_intent=intent)
        assert encoded["packed_f"]["packed"].tolist() == ["A|-|B"]
        decoded = decode_cell_values(encoded, source="packed_f", output="round", codec_intent=intent)
        assert decoded["round"][["a", "b", "c"]].to_dict(orient="records") == [
            {"a": "A", "b": "", "c": "B"}
        ]


class TestHistoricalDeclarationValidation:
    """I1/I2/I3: historical declaration validation before data shortcuts."""

    def test_split_tokens_empty_group_encode_validates_delimiter(self) -> None:
        # I1: delimiter="" must fail even for an all-empty group (empty fast
        # path must not skip delimiter validation).
        with pytest.raises(ValueError, match="non-empty delimiter"):
            encode_cell_values(
                {"s": pd.DataFrame([{"g": "G", "code": ""}])},
                source="s",
                output="out",
                group_by="g",
                mode="split_tokens",
                delimiter="",
            )

    def test_split_tokens_empty_cell_decode_validates_delimiter(self) -> None:
        # I1: delimiter="" must fail for an empty compact cell with
        # drop_empty=False (data-independent declaration validity).
        with pytest.raises(ValueError, match="non-empty delimiter"):
            decode_cell_values(
                {"s": pd.DataFrame([{"id": "1", "value": ""}])},
                source="s",
                output="out",
                mode="split_tokens",
                delimiter="",
                drop_empty=False,
            )

    def test_duplicate_passthrough_declarations_rejected(self) -> None:
        # I2: duplicate passthrough must never create duplicate output columns.
        with pytest.raises(ValueError, match="duplicate field"):
            decode_cell_values(
                {"s": pd.DataFrame([{"id": "1", "value": "x"}])},
                source="s",
                output="out",
                mode="whole_cell_code",
                passthrough_columns=["id", "id"],
            )

    def test_codec_intent_with_historical_mode_rejected(self) -> None:
        # I3: mutual exclusion enforced, not silent position precedence.
        with pytest.raises(ValueError, match="mutually exclusive"):
            encode_cell_values(
                {"s": pd.DataFrame([{"a": "x"}])},
                source="s",
                output="out",
                codec_intent={
                    "participating_columns": ["a"],
                    "compact_column": "p",
                    "separator": "|",
                    "absent_value": "-",
                },
                mode="whole_cell_code",
                group_by="a",
            )

    def test_codec_intent_with_historical_group_by_rejected(self) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            decode_cell_values(
                {"s": pd.DataFrame([{"a": "x", "p": "y"}])},
                source="s",
                output="out",
                codec_intent={
                    "participating_columns": ["a"],
                    "compact_column": "p",
                    "separator": "|",
                    "absent_value": "-",
                },
                passthrough_columns=["a"],
            )

    def test_codec_intent_alone_still_works(self) -> None:
        # Untouched historical defaults are not caller intent: position path
        # works with only codec_intent supplied.
        out = encode_cell_values(
            {"s": pd.DataFrame([{"a": "A", "b": "B"}])},
            source="s",
            output="out",
            codec_intent={
                "participating_columns": ["a", "b"],
                "compact_column": "p",
                "separator": "|",
                "absent_value": "-",
            },
        )
        assert out["out"]["p"].tolist() == ["A|B"]


class TestEffectiveValueMutualExclusion:
    """R002-I3: effective-value mutual exclusion + typed public signatures."""

    @staticmethod
    def _pos() -> dict:
        return {
            "participating_columns": ["a", "b"],
            "compact_column": "p",
            "separator": "|",
            "absent_value": "-",
        }

    def _frames(self) -> dict:
        return {"s": pd.DataFrame([{"a": "A", "b": "B"}])}

    def test_historical_defaults_alongside_codec_intent_allowed(self) -> None:
        # Explicit historical values equal to their public defaults carry no
        # distinct historical intent: the position path runs.
        out = encode_cell_values(
            self._frames(),
            source="s",
            output="out",
            codec_intent=self._pos(),
            delimiter="-",
            strip=False,
            code="code",
            value="value",
        )
        assert out["out"]["p"].tolist() == ["A|B"]

    def test_decode_historical_defaults_alongside_codec_intent_allowed(self) -> None:
        frames = {"s": pd.DataFrame([{"p": "A|B"}])}
        out = decode_cell_values(
            frames,
            source="s",
            output="out",
            codec_intent=self._pos(),
            delimiter="-",
            drop_empty=True,
            strip=False,
        )
        assert out["out"][["a", "b"]].to_dict(orient="records") == [{"a": "A", "b": "B"}]

    def test_nondefault_delimiter_alongside_codec_intent_rejected(self) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            encode_cell_values(
                self._frames(), source="s", output="out",
                codec_intent=self._pos(), delimiter=";",
            )

    def test_strip_true_alongside_codec_intent_rejected(self) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            encode_cell_values(
                self._frames(), source="s", output="out",
                codec_intent=self._pos(), strip=True,
            )

    def test_allowed_tokens_alongside_codec_intent_rejected(self) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            encode_cell_values(
                self._frames(), source="s", output="out",
                codec_intent=self._pos(), allowed_tokens=["A"],
            )

    def test_public_signatures_expose_typed_defaults_not_sentinel(self) -> None:
        import inspect

        for fn in (encode_cell_values, decode_cell_values):
            rendered = str(inspect.signature(fn))
            assert "unset" not in rendered.lower(), rendered
            params = inspect.signature(fn).parameters
            assert params["delimiter"].default == "-"
            assert params["strip"].default is False
            assert params["mode"].default is None
            assert params["code"].default == "code"


class TestGeneratedOutputLabelBoundary:
    """R002-B1: historical generated output labels are validated.

    Historical decode's generated `code` label and historical encode's
    generated `value` label reach the shared scalar-addressability boundary
    before collision/membership/record/output construction.
    """

    @staticmethod
    def _assert_clean(frames: dict, before_meta: object) -> None:
        assert "out" not in frames
        assert frames.get("_meta") == before_meta

    @pytest.mark.parametrize(
        "bad",
        [[1, 2], pd.NA, None, np.array([1, 2])],
        ids=["list", "pd_NA", "None", "ndarray"],
    )
    def test_decode_generated_code_label_rejected(self, bad: object) -> None:
        frames = {"s": pd.DataFrame([{"id": "r", "value": "A"}]), "_meta": {"k": 1}}
        before = copy.deepcopy(frames["_meta"])
        before_frame = frames["s"].copy()
        with pytest.raises(ValueError, match="cannot address a scalar column"):
            decode_cell_values(
                frames, source="s", output="out", mode="whole_cell_code", code=bad,
            )
        self._assert_clean(frames, before)
        assert frames["s"].equals(before_frame)

    @pytest.mark.parametrize(
        "bad",
        [[1, 2], pd.NA, None, np.array([1, 2])],
        ids=["list", "pd_NA", "None", "ndarray"],
    )
    def test_encode_generated_value_label_rejected(self, bad: object) -> None:
        frames = {"s": pd.DataFrame([{"g": "G", "code": "A"}]), "_meta": {"k": 1}}
        before = copy.deepcopy(frames["_meta"])
        before_frame = frames["s"].copy()
        with pytest.raises(ValueError, match="cannot address a scalar column"):
            encode_cell_values(
                frames, source="s", output="out", group_by="g",
                mode="whole_cell_code", value=bad,
            )
        self._assert_clean(frames, before)
        assert frames["s"].equals(before_frame)

    def test_decode_ordinary_string_code_label_supported(self) -> None:
        out = decode_cell_values(
            {"s": pd.DataFrame([{"id": "r", "value": "A"}])},
            source="s", output="out", mode="whole_cell_code", code="mycode",
        )
        assert list(out["out"].columns) == ["id", "mycode"]

    def test_encode_numeric_value_label_supported(self) -> None:
        # Generated output labels are not string-only; a numeric scalar label
        # is scalar-addressable.
        out = encode_cell_values(
            {"s": pd.DataFrame([{"g": "G", "code": "A"}])},
            source="s", output="out", group_by="g", mode="whole_cell_code", value=7,
        )
        assert 7 in out["out"].columns
