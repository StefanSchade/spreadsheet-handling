"""Protect the bounded structural model used by pipeline metadata tracing."""

from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.pipeline._meta_change_trace import diff_meta, format_meta_diff, snapshot_meta

pytestmark = pytest.mark.ftr("FTR-PIPELINE-META-CHANGE-TRACE-P5")


def _diff(before: object, after: object):
    return diff_meta(snapshot_meta({"_meta": before}), snapshot_meta({"_meta": after}))


def test_unchanged_metadata_has_compact_structured_outcome() -> None:
    result = _diff({"policy": {"enabled": True}}, {"policy": {"enabled": True}})

    assert result.unchanged
    assert result.added == ()
    assert result.changed == ()
    assert result.removed == ()


def test_added_root_collapses_its_entire_subtree() -> None:
    result = _diff({}, {"workbook_view": {"sheets": [{"frame": "places"}]}})

    assert result.added == (("workbook_view",),)


def test_added_nested_mapping_reports_the_highest_new_nested_path() -> None:
    result = _diff({"policy": {}}, {"policy": {"mode": {"strict": True}}})

    assert result.added == (("policy", "mode"),)


def test_changed_nested_mapping_reports_leaf_path() -> None:
    result = _diff({"policy": {"mode": "old"}}, {"policy": {"mode": "new"}})

    assert result.changed == (("policy", "mode"),)


def test_removed_subtree_collapses_to_highest_removed_path() -> None:
    result = _diff({"transient": {"nested": {"flag": True}}}, {})

    assert result.removed == (("transient",),)


def test_paths_are_sorted_deterministically_by_dotted_rendering() -> None:
    result = _diff(
        {"zeta": 1, "nested": {"zeta": 1, "alpha": 1}},
        {"alpha": 1, "nested": {"zeta": 2, "beta": 1}},
    )

    assert result.added == (("alpha",), ("nested", "beta"))
    assert result.changed == (("nested", "zeta"),)
    assert result.removed == (("nested", "alpha"), ("zeta",))


def test_formatter_emits_structural_paths_without_metadata_values() -> None:
    result = _diff({"policy": {"mode": "SECRET-BEFORE"}}, {"policy": {"mode": "SECRET-AFTER"}})

    summary = format_meta_diff("configure_policy", result)

    assert "configure_policy" in summary
    assert "policy.mode" in summary
    assert "SECRET-BEFORE" not in summary
    assert "SECRET-AFTER" not in summary


def test_snapshot_detects_nested_in_place_dictionary_mutation() -> None:
    metadata = {"frame_lifecycle": {"places": {"kind": "source"}}}
    before = snapshot_meta({"_meta": metadata})
    metadata["frame_lifecycle"]["places"]["kind"] = "derived"

    result = diff_meta(before, snapshot_meta({"_meta": metadata}))

    assert result.changed == (("frame_lifecycle", "places", "kind"),)


def test_nested_in_place_list_mutation_reports_only_sequence_container() -> None:
    metadata = {"helper_policies": {"fk": {"relations": [{"source": "places"}]}}}
    before = snapshot_meta({"_meta": metadata})
    metadata["helper_policies"]["fk"]["relations"][0]["source"] = "characters"

    result = diff_meta(before, snapshot_meta({"_meta": metadata}))

    assert result.changed == (("helper_policies", "fk", "relations"),)
    assert all("0" not in path for path in result.changed)


def test_tuple_snapshot_detects_mutation_inside_nested_member_at_tuple_path() -> None:
    nested = {"mode": "before"}
    metadata = {"policy": {"rules": (nested,)}}
    before = snapshot_meta({"_meta": metadata})
    nested["mode"] = "after"

    result = diff_meta(before, snapshot_meta({"_meta": metadata}))

    assert result.changed == (("policy", "rules"),)


def test_list_and_tuple_type_change_is_atomic_at_container() -> None:
    result = _diff({"policy": {"rules": ["a"]}}, {"policy": {"rules": ("a",)}})

    assert result.changed == (("policy", "rules"),)


def test_safe_scalars_handle_nan_without_false_changes() -> None:
    unchanged = _diff({"value": float("nan"), "enabled": True}, {"value": float("nan"), "enabled": True})
    changed = _diff({"value": 1}, {"value": 2})

    assert unchanged.unchanged
    assert changed.changed == (("value",),)


def test_safe_set_mutation_is_detected_atomically() -> None:
    metadata = {"policy": {"roles": {"source", "derived"}}}
    before = snapshot_meta({"_meta": metadata})
    metadata["policy"]["roles"].add("transient")

    result = diff_meta(before, snapshot_meta({"_meta": metadata}))

    assert result.changed == (("policy", "roles"),)


def test_opaque_objects_use_identity_without_equality_or_representation() -> None:
    class Opaque:
        def __eq__(self, other: object) -> bool:
            raise AssertionError("equality must not be called")

        def __repr__(self) -> str:
            raise AssertionError("repr must not be called")

    value = Opaque()
    unchanged = _diff({"opaque": value}, {"opaque": value})
    changed = _diff({"opaque": value}, {"opaque": Opaque()})

    assert unchanged.unchanged
    assert changed.changed == (("opaque",),)


def test_unsupported_mapping_key_collapses_to_safe_parent_with_limitation() -> None:
    class UnsafeKey:
        def __repr__(self) -> str:
            raise AssertionError("repr must not be called")

    key = UnsafeKey()
    metadata = {"policy": {key: "before"}}
    before = snapshot_meta({"_meta": metadata})
    metadata["policy"][key] = "after"

    result = diff_meta(before, snapshot_meta({"_meta": metadata}))

    assert result.changed == (("policy",),)
    assert result.limited
    assert all(segment == "policy" for path in result.changed for segment in path)


def test_absent_meta_is_safe_and_empty_until_a_root_is_added() -> None:
    absent = snapshot_meta({"frame": pd.DataFrame()})

    assert diff_meta(absent, snapshot_meta({"frame": pd.DataFrame()})).unchanged
    assert diff_meta(absent, snapshot_meta({"_meta": {"policy": {"mode": "strict"}}})).added == (
        ("policy",),
    )


def test_dataframe_is_opaque_and_never_deep_copied(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = pd.DataFrame({"secret": ["value"]})

    def fail_deepcopy(self: pd.DataFrame, memo: object) -> object:
        raise AssertionError("DataFrame deepcopy must not be called")

    monkeypatch.setattr(pd.DataFrame, "__deepcopy__", fail_deepcopy)
    before = snapshot_meta({"_meta": {"opaque_frame": frame}})
    unchanged = diff_meta(before, snapshot_meta({"_meta": {"opaque_frame": frame}}))
    replaced = diff_meta(before, snapshot_meta({"_meta": {"opaque_frame": frame.copy()}}))

    assert unchanged.unchanged
    assert replaced.changed == (("opaque_frame",),)
