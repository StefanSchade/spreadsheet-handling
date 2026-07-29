"""Scoped recomposition (base_canonical_relation) for Compact Multiaxis.

FTR-COMPACT-MULTIAXIS-SCOPED-RECOMPOSITION-P4A: a partial spreadsheet
projection reimported against a supplied canonical base relation must preserve
out-of-scope canonical rows and replace exactly the visible scope, by composing
Cell Codec encode + XRef ``base_relation`` scoped recomposition + Cell Codec
decode. No parallel merge logic lives in Compact Multiaxis.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
import pytest

import spreadsheet_handling.domain.transformations.compact_multiaxis as cm
from spreadsheet_handling.domain.transformations.compact_multiaxis import (
    expand_compact_multiaxis,
)


pytestmark = pytest.mark.ftr("FTR-COMPACT-MULTIAXIS-SCOPED-RECOMPOSITION-P4A")


def _legend_meta() -> dict[str, Any]:
    return {
        "legend_blocks": {
            "codes": {
                "entries": [
                    {"token": "E", "label": "Editable", "group": "input"},
                    {"token": "K", "label": "Key", "group": "input"},
                    {"token": "S", "label": "System", "group": "system"},
                ],
            }
        }
    }


def _canonical_base() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"feature_id": "f1", "column_key": "P-001", "code": "E"},
            {"feature_id": "f1", "column_key": "P-002", "code": "K"},
            {"feature_id": "f1", "column_key": "P-003", "code": "S"},
        ]
    )


def _assert_no_internal_temp_reference(value: Any) -> None:
    if isinstance(value, str):
        assert "__compact_multiaxis_" not in value
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_no_internal_temp_reference(key)
            _assert_no_internal_temp_reference(child)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            _assert_no_internal_temp_reference(child)


# --- Compatibility: no base supplied ---------------------------------------


def test_no_base_relation_reproduces_pre_ftr_full_replacement() -> None:
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["Z"]}),
        "base": _canonical_base(),
    }

    without_base = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
    )

    # Default behavior: only the visible scope; out-of-scope rows are not
    # recoverable (the pre-FTR contract).
    assert without_base["rel"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "Z"},
    ]
    assert (
        "base_canonical_relation"
        not in without_base["_meta"]["compact_multiaxis"]["rel"]
    )


# --- Core preservation ------------------------------------------------------


def test_partial_projection_preserves_out_of_scope_rows() -> None:
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["Z"]}),
        "base": _canonical_base(),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        base_canonical_relation="base",
    )

    # Edited P-001 comes from the matrix (Z, not the base E); P-002/P-003 survive.
    assert out["rel"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "Z"},
        {"feature_id": "f1", "column_key": "P-002", "code": "K"},
        {"feature_id": "f1", "column_key": "P-003", "code": "S"},
    ]
    # Exactly one P-001 row: no duplicate base row within visible scope.
    p001 = [r for r in out["rel"].to_dict(orient="records") if r["column_key"] == "P-001"]
    assert len(p001) == 1


def test_full_projection_with_base_has_no_duplicate_base_rows() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {"feature_id": ["f1"], "P-001": ["E"], "P-002": ["K"], "P-003": ["S"]}
        ),
        "base": _canonical_base(),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        base_canonical_relation="base",
    )

    # Whole scope is matrix-owned: result equals the visible scope, no dup rows.
    assert out["rel"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E"},
        {"feature_id": "f1", "column_key": "P-002", "code": "K"},
        {"feature_id": "f1", "column_key": "P-003", "code": "S"},
    ]


def test_deletion_inside_visible_scope_removes_matching_row() -> None:
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": [""]}),
        "base": _canonical_base(),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        base_canonical_relation="base",
    )

    # The cleared in-scope P-001 address is removed and does not resurrect from
    # the base; unrelated out-of-scope rows survive.
    assert out["rel"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-002", "code": "K"},
        {"feature_id": "f1", "column_key": "P-003", "code": "S"},
    ]


def test_deletion_with_drop_empty_false_keeps_truthful_empty_row() -> None:
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": [""]}),
        "base": _canonical_base(),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        base_canonical_relation="base",
        drop_empty=False,
    )

    # XRef's non-dropping expansion still suppresses the matching base address.
    # The caller's codec policy then retains one truthful empty canonical row.
    assert out["rel"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": ""},
        {"feature_id": "f1", "column_key": "P-002", "code": "K"},
        {"feature_id": "f1", "column_key": "P-003", "code": "S"},
    ]


def test_new_address_inside_visible_scope_is_added() -> None:
    base = pd.DataFrame(
        [
            {"feature_id": "f1", "column_key": "P-002", "code": "K"},
        ]
    )
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["E"]}),
        "base": base,
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        base_canonical_relation="base",
    )

    assert out["rel"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E"},
        {"feature_id": "f1", "column_key": "P-002", "code": "K"},
    ]


def test_ordering_is_in_scope_then_out_of_scope() -> None:
    base = pd.DataFrame(
        [
            {"feature_id": "f1", "column_key": "P-003", "code": "S"},
            {"feature_id": "f1", "column_key": "P-002", "code": "K"},
            {"feature_id": "f1", "column_key": "P-001", "code": "E"},
        ]
    )
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["Z"]}),
        "base": base,
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        base_canonical_relation="base",
    )

    # In-scope P-001 first, then out-of-scope rows in base first-occurrence order.
    assert out["rel"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "Z"},
        {"feature_id": "f1", "column_key": "P-003", "code": "S"},
        {"feature_id": "f1", "column_key": "P-002", "code": "K"},
    ]


def test_duplicate_visible_and_base_address_lets_visible_win() -> None:
    # Base carries P-001 = E; the visible matrix overrides it with Z.
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["Z"]}),
        "base": pd.DataFrame(
            [
                {"feature_id": "f1", "column_key": "P-001", "code": "E"},
            ]
        ),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        base_canonical_relation="base",
    )

    assert out["rel"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "Z"},
    ]


# --- Codec modes ------------------------------------------------------------


def test_split_tokens_mode_honored_on_base_and_merged_decode() -> None:
    base = pd.DataFrame(
        [
            {"feature_id": "f1", "column_key": "P-001", "code": "E"},
            {"feature_id": "f1", "column_key": "P-002", "code": "K"},
            {"feature_id": "f1", "column_key": "P-002", "code": "S"},
        ]
    )
    frames = {
        # Visible P-001 rewritten to two tokens; P-002 stays in the base.
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["E-K"]}),
        "base": base,
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        mode="split_tokens",
        delimiter="-",
        allowed_tokens=["E", "K", "S"],
        base_canonical_relation="base",
    )

    assert out["rel"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E"},
        {"feature_id": "f1", "column_key": "P-001", "code": "K"},
        {"feature_id": "f1", "column_key": "P-002", "code": "K"},
        {"feature_id": "f1", "column_key": "P-002", "code": "S"},
    ]


def test_group_column_recomputed_for_out_of_scope_rows() -> None:
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["S"]}),
        "base": _canonical_base(),
        "_meta": _legend_meta(),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        allowed_from_legend="codes",
        group="group",
        base_canonical_relation="base",
    )

    # The out-of-scope P-002/P-003 rows get their group recomputed from the
    # legend, exactly like the in-scope rows.
    assert out["rel"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "S", "group": "system"},
        {"feature_id": "f1", "column_key": "P-002", "code": "K", "group": "input"},
        {"feature_id": "f1", "column_key": "P-003", "code": "S", "group": "system"},
    ]


def test_normalize_case_and_strip_applied_to_base_encode() -> None:
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": [" e "]}),
        "base": pd.DataFrame(
            [
                {"feature_id": "f1", "column_key": "P-002", "code": " k "},
            ]
        ),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        allowed_codes=["E", "K"],
        normalize_case="upper",
        strip=True,
        base_canonical_relation="base",
    )

    # The base code is normalized under the same effective codec configuration
    # as the visible matrix code.
    assert out["rel"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E"},
        {"feature_id": "f1", "column_key": "P-002", "code": "K"},
    ]


# --- Empty projections ------------------------------------------------------


def test_empty_matrix_with_base_preserves_all_base_rows() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {"feature_id": pd.Series([], dtype=object), "P-001": pd.Series([], dtype=object)}
        ),
        "base": _canonical_base(),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        base_canonical_relation="base",
    )

    assert out["rel"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E"},
        {"feature_id": "f1", "column_key": "P-002", "code": "K"},
        {"feature_id": "f1", "column_key": "P-003", "code": "S"},
    ]


def test_empty_base_with_matrix_yields_matrix_scope() -> None:
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["E"]}),
        "base": pd.DataFrame(
            {
                "feature_id": pd.Series([], dtype=object),
                "column_key": pd.Series([], dtype=object),
                "code": pd.Series([], dtype=object),
            }
        ),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        base_canonical_relation="base",
    )

    assert out["rel"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E"},
    ]


def test_both_empty_yields_empty_relation() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {"feature_id": pd.Series([], dtype=object), "P-001": pd.Series([], dtype=object)}
        ),
        "base": pd.DataFrame(
            {
                "feature_id": pd.Series([], dtype=object),
                "column_key": pd.Series([], dtype=object),
                "code": pd.Series([], dtype=object),
            }
        ),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        base_canonical_relation="base",
    )

    assert out["rel"].to_dict(orient="records") == []


# --- Representation-boundary proof -----------------------------------------


def test_base_is_cell_codec_contracted_before_xref_consumption(monkeypatch) -> None:
    """The base handed to XRef must be the compact encoded relation.

    Narrow monkeypatch spy: it proves the intermediate representation boundary
    (canonical ``code`` shape -> compact ``value`` shape) rather than any
    public behavior, which no behavioral assertion can observe directly.
    """
    captured: dict[str, Any] = {}
    real_expand_xref = cm.expand_xref

    def spy_expand_xref(frames, **kwargs):
        base_name = kwargs.get("base_relation")
        assert base_name is not None
        captured["base_frame"] = frames[base_name].copy(deep=True)
        return real_expand_xref(frames, **kwargs)

    monkeypatch.setattr(cm, "expand_xref", spy_expand_xref)

    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["Z"]}),
        "base": _canonical_base(),
    }
    expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        base_canonical_relation="base",
    )

    base_frame = captured["base_frame"]
    # Compact encoded relation shape: [*row_keys, column_key, value]; the
    # canonical ``code`` column must be gone (it was encoded into ``value``).
    assert list(base_frame.columns) == ["feature_id", "column_key", "value"]
    assert "code" not in base_frame.columns
    assert base_frame.to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "value": "E"},
        {"feature_id": "f1", "column_key": "P-002", "value": "K"},
        {"feature_id": "f1", "column_key": "P-003", "value": "S"},
    ]


# --- Errors, atomicity, metadata hygiene -----------------------------------


def test_invalid_base_code_propagates_codec_error() -> None:
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["E"]}),
        "base": pd.DataFrame(
            [
                {"feature_id": "f1", "column_key": "P-002", "code": "BAD"},
            ]
        ),
    }

    with pytest.raises(ValueError):
        expand_compact_multiaxis(
            frames,
            matrix="matrix",
            output="rel",
            row_keys=["feature_id"],
            value_columns=["P-001"],
            allowed_codes=["E", "K"],
            base_canonical_relation="base",
        )


def test_failure_in_base_encode_preserves_caller_and_prior_trace() -> None:
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["E"]}),
        "base": _canonical_base(),
    }
    # A prior successful run establishes a trace we must not corrupt.
    successful = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        allowed_codes=["E", "K", "S"],
        base_canonical_relation="base",
        name="shared",
    )
    prior_meta = copy.deepcopy(successful["_meta"])
    prior_keys = set(successful)

    bad = dict(successful)
    bad["base"] = pd.DataFrame(
        [
            {"feature_id": "f1", "column_key": "P-002", "code": "BAD"},
        ]
    )
    bad_before = copy.deepcopy(bad["_meta"])

    with pytest.raises(ValueError):
        expand_compact_multiaxis(
            bad,
            matrix="matrix",
            output="rel_failed",
            row_keys=["feature_id"],
            value_columns=["P-001"],
            allowed_codes=["E", "K", "S"],
            base_canonical_relation="base",
            name="shared",
        )

    # Caller mapping and metadata untouched; no temp/partial frame leaked.
    assert bad["_meta"] == bad_before
    assert successful["_meta"] == prior_meta
    assert set(successful) == prior_keys
    assert "rel_failed" not in bad
    assert not any(str(key).startswith("__compact_multiaxis_") for key in bad)


def test_temp_base_frame_never_leaks_into_result_or_metadata() -> None:
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["Z"]}),
        "base": _canonical_base(),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        base_canonical_relation="base",
        name="scoped",
    )

    assert not any(str(key).startswith("__compact_multiaxis_") for key in out)
    _assert_no_internal_temp_reference(out["_meta"])
    # The authored parameter is recorded truthfully (public frame name only).
    trace = out["_meta"]["compact_multiaxis"]["scoped"]
    assert trace["base_canonical_relation"] == "base"


def test_prior_xref_metadata_survives_scoped_recomposition() -> None:
    unrelated = {
        "relation": "other_relation",
        "matrix": "other_matrix",
        "row_keys": ["id"],
        "column_keys": ["B", "A"],
    }
    frames = {
        "matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["Z"]}),
        "base": _canonical_base(),
        "_meta": {"xref_crosstable": {"other": unrelated}},
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="rel",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        base_canonical_relation="base",
        name="scoped",
    )

    # No internal XRef leg persists; unrelated caller entry is preserved.
    assert out["_meta"]["xref_crosstable"] == {"other": unrelated}
    assert "scoped" not in out["_meta"]["xref_crosstable"]
