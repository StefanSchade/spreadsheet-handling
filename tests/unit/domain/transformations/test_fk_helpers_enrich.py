"""Tests for FK-helper enrichment as pure domain transformation.

FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5 refactored the primitives to
consume v2 relation policy at ``_meta.helper_policies.fk``; tests in this
module seed that policy explicitly before invoking ``make_apply_fks_step``.
"""
from __future__ import annotations

import pytest
import pandas as pd

from spreadsheet_handling.core.fk import (
    build_registry,
    build_id_label_maps,
    build_id_value_maps,
    detect_fk_columns,
    apply_fk_helpers,
    _materialize_fk_helpers,
)
from spreadsheet_handling.core.indexing import level0_series
from spreadsheet_handling.domain.fk_relations import infer_fk_relations
from spreadsheet_handling.domain.helper_policies import configure_fk_helpers
from spreadsheet_handling.pipeline.steps import make_apply_fks_step

pytestmark = pytest.mark.ftr("FTR-FK-HELPER-REFACTOR-P3B")

DEFAULTS = {"id_field": "id", "label_field": "name", "helper_prefix": "_"}


def _frames():
    b = pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]})
    a = pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]})
    return {"A": a, "B": b}


def _frames_with_v2_policy(*, helper_fields: list[str] | None = None):
    frames = _frames()
    if helper_fields is not None:
        return configure_fk_helpers(
            frames,
            target="B",
            key="id",
            allowed_helpers=helper_fields,
            default_helpers=helper_fields,
        )
    return infer_fk_relations(frames)


class TestApplyFkHelpers:
    """Materialization unit tests stay on the legacy core/fk helpers.

    These tests cover the lower-level ``apply_fk_helpers`` building block; they
    remain unchanged because that helper is still used by the v2-aware
    primitive to write declared helper columns.
    """

    def test_adds_helper_column(self):
        frames = _frames()
        reg = build_registry(frames, DEFAULTS)
        id_maps = build_id_label_maps(frames, reg)
        fk_defs = detect_fk_columns(frames["A"], reg, helper_prefix="_")

        result = apply_fk_helpers(frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_")
        assert "_B_name" in [c[0] if isinstance(c, tuple) else c for c in result.columns]

    def test_helper_values_match_lookup(self):
        frames = _frames()
        reg = build_registry(frames, DEFAULTS)
        id_maps = build_id_label_maps(frames, reg)
        fk_defs = detect_fk_columns(frames["A"], reg, helper_prefix="_")

        result = apply_fk_helpers(frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_")
        helper_col = [c for c in result.columns if (c[0] if isinstance(c, tuple) else c) == "_B_name"][0]
        helpers = result[helper_col].tolist()
        assert helpers == ["alpha", "beta"]

    def test_no_fk_columns_returns_unchanged(self):
        df = pd.DataFrame({"id": [1], "value": ["x"]})
        reg = build_registry({"X": df}, DEFAULTS)
        id_maps = build_id_label_maps({"X": df}, reg)
        fk_defs = detect_fk_columns(df, reg, helper_prefix="_")
        assert fk_defs == []
        result = apply_fk_helpers(df, fk_defs, id_maps, levels=1)
        assert list(result.columns) == ["id", "value"]

    def test_detect_fk_disabled_skips(self):
        frames = _frames()
        reg = build_registry(frames, DEFAULTS)
        fk_defs = detect_fk_columns(frames["A"], {}, helper_prefix="_")
        assert fk_defs == []

    def test_adds_multiple_helper_columns_in_configured_order(self):
        frames = {
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
            "B": pd.DataFrame(
                {
                    "id": [1, 2],
                    "name": ["alpha", "beta"],
                    "category": ["x", "y"],
                }
            ),
        }
        defaults = {
            **DEFAULTS,
            "helper_fields_by_fk": {"id_(B)": ["category", "name"]},
        }
        reg = build_registry(frames, defaults)
        fk_defs = detect_fk_columns(frames["A"], reg, helper_prefix="_", defaults=defaults)
        id_maps = build_id_value_maps(frames, reg, fields_by_sheet={"B": ["category", "name"]})

        result = apply_fk_helpers(frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_")
        lvl0 = [c[0] if isinstance(c, tuple) else c for c in result.columns]

        assert lvl0 == ["id", "id_(B)", "_B_category", "_B_name"]
        assert level0_series(result, "_B_category").tolist() == ["x", "y"]
        assert level0_series(result, "_B_name").tolist() == ["alpha", "beta"]


class TestMaterializeFkHelpersReport:
    """FK Helper Deletion Authority design, Slice 1 (<<E>>, <<N>>, <<O>>).

    ``_materialize_fk_helpers`` is the private reporting primitive backing
    ``apply_fk_helpers``. It must report, per requested FK definition,
    whether this call actually materialized the helper column or skipped it
    because the requested label already existed -- the mechanical fact
    Slice 2 needs for truthful provenance. This slice only proves the
    mechanical report; it does not touch Domain provenance behavior.
    """

    def test_absent_label_is_materialized_and_not_skipped(self):
        frames = _frames()
        reg = build_registry(frames, DEFAULTS)
        id_maps = build_id_label_maps(frames, reg)
        fk_defs = detect_fk_columns(frames["A"], reg, helper_prefix="_")

        result = _materialize_fk_helpers(
            frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_"
        )

        assert "_B_name" in [
            c[0] if isinstance(c, tuple) else c for c in result.frame.columns
        ]
        assert result.materialized == fk_defs
        assert result.skipped_existing == []

    def test_pre_existing_label_is_skipped_and_not_materialized(self):
        frames = _frames()
        # Pre-occupy the requested helper label exactly as a caller-supplied
        # column would; the existing collision behavior must leave it
        # untouched and claim nothing.
        frames["A"]["_B_name"] = ["preexisting", "values"]
        reg = build_registry(frames, DEFAULTS)
        id_maps = build_id_label_maps(frames, reg)
        fk_defs = detect_fk_columns(frames["A"], reg, helper_prefix="_")

        result = _materialize_fk_helpers(
            frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_"
        )

        helper_col = [
            c for c in result.frame.columns
            if (c[0] if isinstance(c, tuple) else c) == "_B_name"
        ][0]
        assert result.frame[helper_col].tolist() == ["preexisting", "values"]
        assert result.materialized == []
        assert result.skipped_existing == fk_defs

    def test_mixed_definitions_report_each_independently(self):
        frames = {
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
            "B": pd.DataFrame(
                {
                    "id": [1, 2],
                    "name": ["alpha", "beta"],
                    "category": ["x", "y"],
                }
            ),
        }
        # Pre-occupy only one of the two requested helper labels.
        frames["A"]["_B_category"] = ["pre-x", "pre-y"]
        defaults = {
            **DEFAULTS,
            "helper_fields_by_fk": {"id_(B)": ["category", "name"]},
        }
        reg = build_registry(frames, defaults)
        fk_defs = detect_fk_columns(
            frames["A"], reg, helper_prefix="_", defaults=defaults
        )
        id_maps = build_id_value_maps(
            frames, reg, fields_by_sheet={"B": ["category", "name"]}
        )
        category_def = next(fk for fk in fk_defs if fk.value_field == "category")
        name_def = next(fk for fk in fk_defs if fk.value_field == "name")

        result = _materialize_fk_helpers(
            frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_"
        )

        assert result.materialized == [name_def]
        assert result.skipped_existing == [category_def]
        assert level0_series(result.frame, "_B_category").tolist() == [
            "pre-x",
            "pre-y",
        ]
        assert level0_series(result.frame, "_B_name").tolist() == ["alpha", "beta"]

    def test_apply_fk_helpers_wrapper_returns_same_frame_as_report(self):
        frames = _frames()
        reg = build_registry(frames, DEFAULTS)
        id_maps = build_id_label_maps(frames, reg)
        fk_defs = detect_fk_columns(frames["A"], reg, helper_prefix="_")

        wrapped = apply_fk_helpers(
            frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_"
        )
        reported = _materialize_fk_helpers(
            frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_"
        ).frame

        assert isinstance(wrapped, pd.DataFrame)
        pd.testing.assert_frame_equal(wrapped, reported)


class TestApplyFkHelpersUnresolvedCarrier:
    """BUG-UNRESOLVED-HELPER-VALUE-NAN-SEMANTICS-P4A: unresolved-lookup carrier.

    Unit-level guard for the write-boundary normalization in
    ``apply_fk_helpers``, independent of the roundtrip layer. Before the
    fix, an unresolved lookup produced Python ``None``, which pandas column
    assignment silently coerced into a real ``float('nan')`` carrier -- the
    root cause of the backend-divergent "nan"/"" corruption on write.
    ``apply_fk_helpers`` now supplies an explicit ``""`` default for a
    lookup *miss*, so a lookup miss no longer introduces a pandas missing
    carrier. A successful lookup still returns its stored target payload
    verbatim: if that payload is itself ``None``/NaN/pandas-``NA``, the
    helper column can still carry a missing value for that row -- that
    case is outside this slice (see
    ``TestMissingLabelField::test_missing_label_field_results_in_none_helper``
    in ``test_fk_edge_cases.py``).
    """

    def test_unresolved_non_empty_key_produces_plain_empty_string(self):
        """A well-formed but unmatched FK key normalizes to a plain str ''.

        Not ``None``, not ``float('nan')`` -- an ordinary Python string, so
        no backend renderer sees a pandas missing carrier for this row's
        lookup miss. (A different, successfully resolved row in the same
        column could still carry a missing carrier if its stored target
        payload is itself missing -- outside this test's scope.)
        """
        frames = {
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 99]}),
            "B": pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]}),
        }
        reg = build_registry(frames, DEFAULTS)
        id_maps = build_id_label_maps(frames, reg)
        fk_defs = detect_fk_columns(frames["A"], reg, helper_prefix="_")

        result = apply_fk_helpers(frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_")
        helper_col = [c for c in result.columns if (c[0] if isinstance(c, tuple) else c) == "_B_name"][0]
        values = result[helper_col].tolist()

        assert values == ["alpha", ""]
        unresolved = values[1]
        assert unresolved == ""
        assert isinstance(unresolved, str)
        assert not (isinstance(unresolved, float) and pd.isna(unresolved))

    def test_missing_source_key_produces_plain_empty_string(self):
        """A missing/None FK source key (carrier-missing, not merely unmatched)
        normalizes to the same plain str '' -- covered separately from the
        non-empty unresolved-key case above, per the family contract's
        distinction between the two upstream causes.
        """
        # String-typed ids avoid pandas' int-to-float upcast that a mixed
        # ``[int, None]`` column would otherwise trigger for *all* rows
        # (turning a resolvable ``1`` into ``1.0``, which would no longer
        # match a target id of ``"1"``) -- that upcast is an unrelated
        # pandas dtype artifact of this test's own column construction, not
        # the carrier defect under test here.
        frames = {
            "A": pd.DataFrame({"id": ["10", "20"], "id_(B)": ["b1", None]}),
            "B": pd.DataFrame({"id": ["b1", "b2"], "name": ["alpha", "beta"]}),
        }
        reg = build_registry(frames, DEFAULTS)
        id_maps = build_id_label_maps(frames, reg)
        fk_defs = detect_fk_columns(frames["A"], reg, helper_prefix="_")

        result = apply_fk_helpers(frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_")
        helper_col = [c for c in result.columns if (c[0] if isinstance(c, tuple) else c) == "_B_name"][0]
        values = result[helper_col].tolist()

        assert values == ["alpha", ""]
        assert isinstance(values[1], str)

    def test_literal_domain_nan_target_value_preserved(self):
        """A resolved match whose target value is literally 'nan' stays 'nan'.

        The fix detects the missing *carrier*; it must not censor the
        spelling "nan" for a legitimate resolved dict hit.
        """
        frames = {
            "A": pd.DataFrame({"id": [10], "id_(B)": [1]}),
            "B": pd.DataFrame({"id": [1], "name": ["nan"]}),
        }
        reg = build_registry(frames, DEFAULTS)
        id_maps = build_id_label_maps(frames, reg)
        fk_defs = detect_fk_columns(frames["A"], reg, helper_prefix="_")

        result = apply_fk_helpers(frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_")
        helper_col = [c for c in result.columns if (c[0] if isinstance(c, tuple) else c) == "_B_name"][0]
        assert result[helper_col].tolist() == ["nan"]

    def test_legitimate_empty_string_target_value_preserved(self):
        """A resolved match whose target value is a legitimate '' stays ''.

        A dict hit, not the unresolved-lookup default -- the resolved path
        must keep returning the real stored value.
        """
        frames = {
            "A": pd.DataFrame({"id": [10], "id_(B)": [1]}),
            "B": pd.DataFrame({"id": [1], "name": [""]}),
        }
        reg = build_registry(frames, DEFAULTS)
        id_maps = build_id_label_maps(frames, reg)
        fk_defs = detect_fk_columns(frames["A"], reg, helper_prefix="_")

        result = apply_fk_helpers(frames["A"], fk_defs, id_maps, levels=1, helper_prefix="_")
        helper_col = [c for c in result.columns if (c[0] if isinstance(c, tuple) else c) == "_B_name"][0]
        assert result[helper_col].tolist() == [""]


class TestApplyFksStepProvenance:
    """FTR-FK-HELPER-PROVENANCE-CLEANUP: apply_fks writes derived provenance."""

    def test_provenance_written_for_single_helper(self):
        frames = _frames_with_v2_policy()
        step = make_apply_fks_step(defaults=DEFAULTS)
        out = step.fn(frames)

        meta = out["_meta"]
        prov = meta["derived"]["sheets"]["A"]["helper_columns"]
        assert len(prov) == 1
        assert prov[0] == {
            "column": "_B_name",
            "fk_column": "id_(B)",
            "target": "B",
            "target_key": "id",
            "value_field": "name",
        }

    def test_provenance_written_for_multiple_helpers_in_order(self):
        frames = {
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
            "B": pd.DataFrame(
                {"id": [1, 2], "name": ["alpha", "beta"], "category": ["x", "y"]}
            ),
        }
        configured = configure_fk_helpers(
            frames,
            target="B",
            key="id",
            allowed_helpers=["category", "name"],
            default_helpers=["category", "name"],
        )
        step = make_apply_fks_step(defaults=DEFAULTS)
        out = step.fn(configured)

        prov = out["_meta"]["derived"]["sheets"]["A"]["helper_columns"]
        assert len(prov) == 2
        assert prov[0]["column"] == "_B_category"
        assert prov[1]["column"] == "_B_name"
        assert prov[0]["value_field"] == "category"
        assert prov[1]["value_field"] == "name"

    def test_no_provenance_for_sheet_without_fks(self):
        frames = _frames_with_v2_policy()
        step = make_apply_fks_step(defaults=DEFAULTS)
        out = step.fn(frames)

        derived_sheets = out["_meta"]["derived"]["sheets"]
        assert "B" not in derived_sheets

    def test_provenance_preserves_existing_meta(self):
        frames = _frames_with_v2_policy()
        frames["_meta"].update({"version": "3.0", "author": "test"})
        step = make_apply_fks_step(defaults=DEFAULTS)
        out = step.fn(frames)

        assert out["_meta"]["version"] == "3.0"
        assert out["_meta"]["author"] == "test"
        assert "derived" in out["_meta"]

    def test_stale_provenance_removed_for_sheet_without_current_fks(self):
        """apply_fks removes stale helper_columns provenance for sheets that
        no longer have FK defs in the current run."""
        frames = _frames_with_v2_policy()
        frames["_meta"]["derived"] = {
            "sheets": {
                "B": {
                    "helper_columns": [
                        {"column": "_X_old", "fk_column": "id_(X)",
                         "target": "X", "target_key": "id", "value_field": "old"},
                    ]
                }
            }
        }
        step = make_apply_fks_step(defaults=DEFAULTS)
        out = step.fn(frames)

        derived_sheets = out["_meta"]["derived"]["sheets"]
        assert "B" not in derived_sheets
        assert "A" in derived_sheets

    def test_stale_provenance_removed_for_sheet_no_longer_in_frames(self):
        """apply_fks cleans provenance for sheets that are not in frames at all."""
        frames = _frames_with_v2_policy()
        frames["_meta"]["derived"] = {
            "sheets": {
                "Gone": {
                    "helper_columns": [
                        {"column": "_Z_val", "fk_column": "id_(Z)",
                         "target": "Z", "target_key": "id", "value_field": "val"},
                    ]
                }
            }
        }
        step = make_apply_fks_step(defaults=DEFAULTS)
        out = step.fn(frames)

        derived_sheets = out["_meta"]["derived"]["sheets"]
        assert "Gone" not in derived_sheets

    def test_key_selective_merge_preserves_other_derived_keys(self):
        """apply_fks only replaces helper_columns, not the whole sheet dict."""
        frames = _frames_with_v2_policy()
        frames["_meta"]["derived"] = {
            "sheets": {
                "A": {"other_derived_key": "keep_me"}
            }
        }
        step = make_apply_fks_step(defaults=DEFAULTS)
        out = step.fn(frames)

        sheet_derived = out["_meta"]["derived"]["sheets"]["A"]
        assert sheet_derived["other_derived_key"] == "keep_me"
        assert "helper_columns" in sheet_derived
