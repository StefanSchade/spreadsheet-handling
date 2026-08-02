from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.enrich_lookup import enrich_lookup


pytestmark = pytest.mark.ftr("FTR-EXPLICIT-HELPER-LOOKUP-POLICY-P4")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _variables() -> pd.DataFrame:
    return pd.DataFrame({
        "ID": ["v1", "v2", "v3"],
        "sort_key": [2, 1, 3],
        "value_label_de": ["Eins", "Zwei", "Drei"],
        "business_component": ["bc1", "bc2", "bc3"],
        "data_type": ["string", "int", "bool"],
        "module": ["m1", "m2", "m3"],
    })


def _matrix_raw() -> pd.DataFrame:
    return pd.DataFrame({
        "ID": ["v1", "v2"],
        "FZ-AD": ["E", ""],
        "FZ-TD": ["", "S"],
    })


def _frames(**extra: pd.DataFrame) -> dict:
    out: dict = {
        "variables": _variables(),
        "variable_usage_matrix_raw": _matrix_raw(),
    }
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# Basic enrichment
# ---------------------------------------------------------------------------

def test_enrich_lookup_projects_explicit_helpers() -> None:
    frames = _frames()
    out = enrich_lookup(
        frames,
        source="variable_usage_matrix_raw",
        lookup="variables",
        output="variable_usage_matrix",
        on="ID",
        helpers={"fields": ["sort_key", "value_label_de", "business_component", "data_type"]},
    )

    result = out["variable_usage_matrix"]
    assert "sort_key" in result.columns
    assert "value_label_de" in result.columns
    assert "business_component" in result.columns
    assert "data_type" in result.columns
    assert "module" not in result.columns
    assert list(result["ID"]) == ["v1", "v2"]


def test_enrich_lookup_sort_by() -> None:
    frames = _frames()
    out = enrich_lookup(
        frames,
        source="variable_usage_matrix_raw",
        lookup="variables",
        output="result",
        on="ID",
        helpers={"fields": ["sort_key", "value_label_de"]},
        order={"sort_by": ["sort_key"]},
    )

    result = out["result"]
    assert list(result["sort_key"]) == [1, 2]
    assert list(result["ID"]) == ["v2", "v1"]


def test_enrich_lookup_helper_position_before_key() -> None:
    frames = _frames()
    out = enrich_lookup(
        frames,
        source="variable_usage_matrix_raw",
        lookup="variables",
        output="result",
        on="ID",
        helpers={"fields": ["sort_key", "value_label_de"]},
        order={"helper_position": "before_key"},
    )

    cols = list(out["result"].columns)
    assert cols.index("sort_key") < cols.index("ID")
    assert cols.index("value_label_de") < cols.index("ID")


def test_enrich_lookup_fills_missing_with_empty_string() -> None:
    """With missing='empty', left join NaN becomes ''."""
    matrix = pd.DataFrame({"ID": ["v1", "v999"], "col": ["a", "b"]})
    frames = _frames(**{"variable_usage_matrix_raw": matrix})
    out = enrich_lookup(
        frames,
        source="variable_usage_matrix_raw",
        lookup="variables",
        output="result",
        on="ID",
        helpers={"fields": ["value_label_de"]},
        missing="empty",
    )

    result = out["result"]
    assert result.loc[result["ID"] == "v999", "value_label_de"].iloc[0] == ""


def test_enrich_lookup_preserves_original_frames() -> None:
    frames = _frames()
    out = enrich_lookup(
        frames,
        source="variable_usage_matrix_raw",
        lookup="variables",
        output="variable_usage_matrix",
        on="ID",
        helpers={"fields": ["sort_key"]},
    )

    assert "variable_usage_matrix_raw" in out
    assert "variables" in out
    assert "variable_usage_matrix" in out


# ---------------------------------------------------------------------------
# Helper policy from _meta
# ---------------------------------------------------------------------------

def test_enrich_lookup_helpers_default_from_policy() -> None:
    frames = _frames(**{
        "_meta": {
            "helper_policies": {
                "lookup": {
                    "variables": {
                        "key": "ID",
                        "allowed_helpers": ["sort_key", "value_label_de", "module"],
                        "default_helpers": ["value_label_de"],
                    }
                }
            }
        }
    })

    out = enrich_lookup(
        frames,
        source="variable_usage_matrix_raw",
        lookup="variables",
        output="result",
        on="ID",
        helpers="default",
    )

    result = out["result"]
    assert "value_label_de" in result.columns
    assert "sort_key" not in result.columns


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------

def test_enrich_lookup_rejects_disallowed_helper() -> None:
    frames = _frames()
    with pytest.raises(ValueError, match="not in allowed list"):
        enrich_lookup(
            frames,
            source="variable_usage_matrix_raw",
            lookup="variables",
            output="result",
            on="ID",
            helpers={
                "fields": ["sort_key", "module"],
                "allowed": ["sort_key", "value_label_de"],
            },
        )


def test_enrich_lookup_allowed_from_policy() -> None:
    frames = _frames(**{
        "_meta": {
            "helper_policies": {
                "lookup": {
                    "variables": {
                        "allowed_helpers": ["sort_key"],
                        "default_helpers": ["sort_key"],
                    }
                }
            }
        }
    })

    with pytest.raises(ValueError, match="not in allowed list"):
        enrich_lookup(
            frames,
            source="variable_usage_matrix_raw",
            lookup="variables",
            output="result",
            on="ID",
            helpers={"fields": ["sort_key", "value_label_de"]},
        )


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_enrich_lookup_missing_source_frame() -> None:
    frames = {"variables": _variables()}
    with pytest.raises(KeyError, match="variable_usage_matrix_raw"):
        enrich_lookup(
            frames,
            source="variable_usage_matrix_raw",
            lookup="variables",
            output="result",
            on="ID",
        )


def test_enrich_lookup_missing_join_key_in_source() -> None:
    frames = {
        "src": pd.DataFrame({"other": [1]}),
        "lkp": pd.DataFrame({"ID": [1]}),
    }
    with pytest.raises(KeyError, match="Join key.*not found in source"):
        enrich_lookup(frames, source="src", lookup="lkp", output="r", on="ID")


def test_enrich_lookup_missing_helper_field_in_lookup() -> None:
    frames = _frames()
    with pytest.raises(KeyError, match="not found in lookup"):
        enrich_lookup(
            frames,
            source="variable_usage_matrix_raw",
            lookup="variables",
            output="result",
            on="ID",
            helpers={"fields": ["nonexistent_column"]},
        )


def test_enrich_lookup_no_helpers_returns_source_joined_on_key() -> None:
    """When helpers=None only the join key intersection is performed."""
    frames = _frames()
    out = enrich_lookup(
        frames,
        source="variable_usage_matrix_raw",
        lookup="variables",
        output="result",
        on="ID",
        helpers=None,
    )
    result = out["result"]
    assert "sort_key" not in result.columns
    assert list(result.columns) == ["ID", "FZ-AD", "FZ-TD"]


# ---------------------------------------------------------------------------
# Multi-key join
# ---------------------------------------------------------------------------

def test_enrich_lookup_multi_key_join() -> None:
    source = pd.DataFrame({"k1": ["a", "b"], "k2": [1, 2], "val": ["x", "y"]})
    lookup = pd.DataFrame({"k1": ["a", "b"], "k2": [1, 2], "label": ["L1", "L2"]})
    frames = {"src": source, "lkp": lookup}

    out = enrich_lookup(
        frames,
        source="src",
        lookup="lkp",
        output="result",
        on=["k1", "k2"],
        helpers={"fields": ["label"]},
    )

    assert list(out["result"]["label"]) == ["L1", "L2"]


@pytest.mark.ftr("FTR-YAML-SAFE-STEP-KEYS-P4")
def test_enrich_lookup_accepts_key_alias() -> None:
    frames = _frames()
    out = enrich_lookup(
        frames,
        source="variable_usage_matrix_raw",
        lookup="variables",
        output="result",
        key="ID",
        helpers={"fields": ["value_label_de"]},
    )

    assert list(out["result"]["value_label_de"]) == ["Eins", "Zwei"]


@pytest.mark.ftr("FTR-YAML-SAFE-STEP-KEYS-P4")
def test_enrich_lookup_accepts_keys_alias() -> None:
    source = pd.DataFrame({"k1": ["a", "b"], "k2": [1, 2], "val": ["x", "y"]})
    lookup = pd.DataFrame({"k1": ["a", "b"], "k2": [1, 2], "label": ["L1", "L2"]})
    frames = {"src": source, "lkp": lookup}

    out = enrich_lookup(
        frames,
        source="src",
        lookup="lkp",
        output="result",
        keys=["k1", "k2"],
        helpers={"fields": ["label"]},
    )

    assert list(out["result"]["label"]) == ["L1", "L2"]


@pytest.mark.ftr("FTR-YAML-SAFE-STEP-KEYS-P4")
def test_enrich_lookup_rejects_multiple_join_key_forms() -> None:
    frames = _frames()
    with pytest.raises(ValueError, match="exactly one"):
        enrich_lookup(
            frames,
            source="variable_usage_matrix_raw",
            lookup="variables",
            output="result",
            key="ID",
            on="ID",
            helpers={"fields": ["value_label_de"]},
        )


# ---------------------------------------------------------------------------
# Finding 1: Duplicate lookup keys
# ---------------------------------------------------------------------------

def test_enrich_lookup_rejects_duplicate_lookup_keys() -> None:
    lookup = pd.DataFrame({"ID": ["v1", "v1", "v2"], "label": ["a", "b", "c"]})
    frames = {"src": _matrix_raw(), "lkp": lookup}
    with pytest.raises(ValueError, match="duplicate keys"):
        enrich_lookup(
            frames,
            source="src",
            lookup="lkp",
            output="result",
            on="ID",
            helpers={"fields": ["label"]},
        )


# ---------------------------------------------------------------------------
# Finding 2: Column collision detection
# ---------------------------------------------------------------------------

def test_enrich_lookup_rejects_column_collision() -> None:
    """Source already has a column that is also requested as helper."""
    source = pd.DataFrame({"ID": ["v1"], "value_label_de": ["existing"]})
    frames = {"src": source, "variables": _variables()}
    with pytest.raises(ValueError, match="already exist in source"):
        enrich_lookup(
            frames,
            source="src",
            lookup="variables",
            output="result",
            on="ID",
            helpers={"fields": ["value_label_de"]},
        )


def test_enrich_lookup_join_key_overlap_not_treated_as_collision() -> None:
    """The join key column exists in both frames by design; that is not a conflict."""
    frames = _frames()
    out = enrich_lookup(
        frames,
        source="variable_usage_matrix_raw",
        lookup="variables",
        output="result",
        on="ID",
        helpers={"fields": ["sort_key"]},
    )
    assert "sort_key" in out["result"].columns


# ---------------------------------------------------------------------------
# Finding 3: missing mode
# ---------------------------------------------------------------------------

def test_enrich_lookup_missing_fail_raises_on_unmatched() -> None:
    matrix = pd.DataFrame({"ID": ["v1", "v999"], "col": ["a", "b"]})
    frames = _frames(**{"variable_usage_matrix_raw": matrix})
    with pytest.raises(ValueError, match="no match in lookup"):
        enrich_lookup(
            frames,
            source="variable_usage_matrix_raw",
            lookup="variables",
            output="result",
            on="ID",
            helpers={"fields": ["value_label_de"]},
            missing="fail",
        )


def test_enrich_lookup_missing_invalid_mode() -> None:
    frames = _frames()
    with pytest.raises(ValueError, match="Invalid missing mode"):
        enrich_lookup(
            frames,
            source="variable_usage_matrix_raw",
            lookup="variables",
            output="result",
            on="ID",
            missing="ignore",
        )


# ---------------------------------------------------------------------------
# Finding 4: Invalid helper_position
# ---------------------------------------------------------------------------

def test_enrich_lookup_rejects_invalid_helper_position() -> None:
    frames = _frames()
    with pytest.raises(ValueError, match="Invalid helper_position"):
        enrich_lookup(
            frames,
            source="variable_usage_matrix_raw",
            lookup="variables",
            output="result",
            on="ID",
            helpers={"fields": ["sort_key"]},
            order={"helper_position": "typo_value"},
        )


# ---------------------------------------------------------------------------
# Finding 5: sort_by missing column
# ---------------------------------------------------------------------------

def test_enrich_lookup_rejects_missing_sort_by_column() -> None:
    frames = _frames()
    with pytest.raises(ValueError, match="sort_by column"):
        enrich_lookup(
            frames,
            source="variable_usage_matrix_raw",
            lookup="variables",
            output="result",
            on="ID",
            helpers={"fields": ["sort_key"]},
            order={"sort_by": ["nonexistent"]},
        )


# ---------------------------------------------------------------------------
# Finding 6: Provenance
# ---------------------------------------------------------------------------

def test_enrich_lookup_writes_only_consumed_helper_provenance() -> None:
    frames = _frames()
    out = enrich_lookup(
        frames,
        source="variable_usage_matrix_raw",
        lookup="variables",
        output="variable_usage_matrix",
        on="ID",
        helpers={"fields": ["sort_key", "value_label_de"]},
    )

    prov = out["_meta"]["derived"]["sheets"]["variable_usage_matrix"]["enrich_lookup"]
    assert prov["lookup"] == "variables"
    assert prov["on"] == ["ID"]
    assert prov["helper_columns"] == ["sort_key", "value_label_de"]
    assert "frame_lifecycle" not in out["_meta"]


def test_enrich_lookup_no_provenance_without_helpers() -> None:
    frames = _frames()
    out = enrich_lookup(
        frames,
        source="variable_usage_matrix_raw",
        lookup="variables",
        output="result",
        on="ID",
        helpers=None,
    )
    meta = out.get("_meta", {})
    derived = meta.get("derived", {}).get("sheets", {})
    assert "result" not in derived


# ---------------------------------------------------------------------------
# FTR-XREF-LOOKUP-HELPER-SUBSTITUTION-P4A2 Slice 1: asymmetric join keys
# ---------------------------------------------------------------------------

pytestmark_asymmetric = pytest.mark.ftr("FTR-XREF-LOOKUP-HELPER-SUBSTITUTION-P4A2")


def _matrix_story() -> pd.DataFrame:
    """Worldbuilding-shaped source: story_id + dynamic matrix-value columns."""
    return pd.DataFrame({
        "story_id": ["s1", "s2"],
        "dynamic_1": ["a", "b"],
        "dynamic_2": ["c", "d"],
    })


def _stories() -> pd.DataFrame:
    """Lookup keyed by ``id`` (not ``story_id``)."""
    return pd.DataFrame({
        "id": ["s1", "s2"],
        "title": ["First", "Second"],
    })


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_source_key_differs_from_lookup_key() -> None:
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="story_id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        missing="empty",
    )

    result = out["result"]
    assert list(result["title"]) == ["First", "Second"]
    # The lookup-side key must not leak into the output.
    assert "id" not in result.columns
    assert "story_id" in result.columns


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_before_key_anchors_on_source_key() -> None:
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="story_id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        order={"helper_position": "before_key"},
        missing="empty",
    )

    assert list(out["result"].columns) == ["title", "story_id", "dynamic_1", "dynamic_2"]


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_after_data_position() -> None:
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="story_id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        order={"helper_position": "after_data"},
        missing="empty",
    )

    assert list(out["result"].columns) == ["story_id", "dynamic_1", "dynamic_2", "title"]


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_default_position_is_after_data() -> None:
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="story_id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        missing="empty",
    )

    assert list(out["result"].columns) == ["story_id", "dynamic_1", "dynamic_2", "title"]


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_missing_source_key() -> None:
    frames = {
        "matrix": pd.DataFrame({"other": ["x"], "dynamic_1": ["a"]}),
        "stories": _stories(),
    }
    with pytest.raises(KeyError, match="Join key 'story_id' not found in source"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["title"]},
        )


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_missing_lookup_key() -> None:
    frames = {
        "matrix": _matrix_story(),
        "stories": pd.DataFrame({"other": ["s1"], "title": ["First"]}),
    }
    with pytest.raises(KeyError, match="Join key 'id' not found in lookup"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["title"]},
        )


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_duplicate_lookup_key() -> None:
    frames = {
        "matrix": _matrix_story(),
        "stories": pd.DataFrame({"id": ["s1", "s1"], "title": ["First", "Dup"]}),
    }
    with pytest.raises(ValueError, match="duplicate keys"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["title"]},
        )


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_unmatched_missing_fail() -> None:
    frames = {
        "matrix": pd.DataFrame({"story_id": ["s1", "s999"], "dynamic_1": ["a", "b"]}),
        "stories": _stories(),
    }
    with pytest.raises(ValueError, match="no match in lookup"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["title"]},
            missing="fail",
        )


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_unmatched_missing_empty() -> None:
    frames = {
        "matrix": pd.DataFrame({"story_id": ["s1", "s999"], "dynamic_1": ["a", "b"]}),
        "stories": _stories(),
    }
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="story_id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        missing="empty",
    )
    result = out["result"]
    assert result.loc[result["story_id"] == "s999", "title"].iloc[0] == ""
    assert result.loc[result["story_id"] == "s1", "title"].iloc[0] == "First"


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_helper_conflict() -> None:
    frames = {
        "matrix": pd.DataFrame({"story_id": ["s1"], "title": ["already"]}),
        "stories": _stories(),
    }
    with pytest.raises(ValueError, match="already exist in source"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["title"]},
        )


@pytestmark_asymmetric
def test_enrich_lookup_rejects_key_with_asymmetric_pair() -> None:
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    with pytest.raises(ValueError, match="not both"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            key="story_id",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["title"]},
        )


@pytestmark_asymmetric
def test_enrich_lookup_rejects_only_source_key() -> None:
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    with pytest.raises(ValueError, match=r"require both.*missing \['lookup_key'\]"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="story_id",
            helpers={"fields": ["title"]},
        )


@pytestmark_asymmetric
def test_enrich_lookup_rejects_only_lookup_key() -> None:
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    with pytest.raises(ValueError, match=r"require both.*missing \['source_key'\]"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            lookup_key="id",
            helpers={"fields": ["title"]},
        )


@pytestmark_asymmetric
def test_enrich_lookup_rejects_blank_source_key() -> None:
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    with pytest.raises(ValueError, match="non-empty key name"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="   ",
            lookup_key="id",
            helpers={"fields": ["title"]},
        )


@pytestmark_asymmetric
def test_enrich_lookup_rejects_non_string_lookup_key() -> None:
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    with pytest.raises(TypeError, match="must be a single string key name"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="story_id",
            lookup_key=123,  # type: ignore[arg-type]
            helpers={"fields": ["title"]},
        )


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_does_not_mutate_caller_frames() -> None:
    matrix = _matrix_story()
    stories = _stories()
    frames = {"matrix": matrix, "stories": stories}
    matrix_before = matrix.copy(deep=True)
    stories_before = stories.copy(deep=True)
    frames_keys_before = set(frames)

    enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="story_id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        order={"helper_position": "before_key"},
        missing="empty",
    )

    pd.testing.assert_frame_equal(matrix, matrix_before)
    pd.testing.assert_frame_equal(stories, stories_before)
    # The caller mapping is not mutated (enrich_lookup returns a new dict).
    assert set(frames) == frames_keys_before
    assert "result" not in frames


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_provenance_records_distinct_keys() -> None:
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="story_id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        missing="empty",
    )

    prov = out["_meta"]["derived"]["sheets"]["result"]["enrich_lookup"]
    assert prov["lookup"] == "stories"
    assert prov["source_key"] == "story_id"
    assert prov["lookup_key"] == "id"
    assert prov["helper_columns"] == ["title"]
    # No misleading synthetic common `on` key in asymmetric mode.
    assert "on" not in prov


@pytestmark_asymmetric
def test_enrich_lookup_symmetric_provenance_unchanged() -> None:
    frames = _frames()
    out = enrich_lookup(
        frames,
        source="variable_usage_matrix_raw",
        lookup="variables",
        output="variable_usage_matrix",
        key="ID",
        helpers={"fields": ["sort_key", "value_label_de"]},
    )

    prov = out["_meta"]["derived"]["sheets"]["variable_usage_matrix"]["enrich_lookup"]
    assert prov == {
        "lookup": "variables",
        "on": ["ID"],
        "helper_columns": ["sort_key", "value_label_de"],
    }


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_generic_dynamic_matrix() -> None:
    """Asymmetric enrichment works for runtime-variable trailing columns."""
    stories = _stories()
    source_a = pd.DataFrame({
        "story_id": ["s1", "s2"],
        "Alpha": ["a1", "a2"],
        "Beta": ["b1", "b2"],
    })
    source_b = pd.DataFrame({
        "story_id": ["s1", "s2"],
        "Beta": ["b1", "b2"],
        "Gamma": ["g1", "g2"],
        "Delta": ["d1", "d2"],
    })

    out_a = enrich_lookup(
        {"matrix": source_a, "stories": stories},
        source="matrix",
        lookup="stories",
        output="result",
        source_key="story_id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        order={"helper_position": "before_key"},
        missing="empty",
    )
    out_b = enrich_lookup(
        {"matrix": source_b, "stories": stories},
        source="matrix",
        lookup="stories",
        output="result",
        source_key="story_id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        order={"helper_position": "before_key"},
        missing="empty",
    )

    assert list(out_a["result"].columns) == ["title", "story_id", "Alpha", "Beta"]
    assert list(out_b["result"].columns) == ["title", "story_id", "Beta", "Gamma", "Delta"]


# ---------------------------------------------------------------------------
# Review 001 IMP-001: asymmetric key/helper collision safety (values mode)
# ---------------------------------------------------------------------------


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_helper_equals_source_key_rejected() -> None:
    """A helper named like the source key would overwrite the authoritative key."""
    stories = pd.DataFrame({"id": ["s1", "s2"], "story_id": ["x", "y"], "title": ["A", "B"]})
    frames = {"matrix": _matrix_story(), "stories": stories}
    with pytest.raises(ValueError, match="collides with the asymmetric source key"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["story_id"]},
            missing="empty",
        )
    # No output frame and no false provenance were written on failure.
    assert "result" not in frames
    assert "_meta" not in frames


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_helper_equals_lookup_key_rejected() -> None:
    """A helper named like the lookup key would leak the lookup key into output."""
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    with pytest.raises(ValueError, match="collides with the asymmetric lookup key"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["id"]},
            missing="empty",
        )
    assert "result" not in frames


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_independent_source_named_lookup_column_is_safe() -> None:
    """An unselected lookup column named like the source key does not collide."""
    stories = pd.DataFrame({
        "id": ["s1", "s2"],
        "story_id": ["ignore-me", "ignore-me-too"],
        "title": ["First", "Second"],
    })
    frames = {"matrix": _matrix_story(), "stories": stories}
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="story_id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        missing="empty",
    )
    result = out["result"]
    assert list(result["title"]) == ["First", "Second"]
    # The source key retains the source values, not the lookup's independent column.
    assert list(result["story_id"]) == ["s1", "s2"]
    assert "id" not in result.columns


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_sort_by_source_key_is_safe() -> None:
    """sort_by on the source key sorts the output key; the lookup's independent
    same-named column is never projected (temporary sort field vs source key)."""
    matrix = pd.DataFrame({"story_id": ["s2", "s1"], "dynamic_1": ["b", "a"]})
    stories = pd.DataFrame({
        "id": ["s1", "s2"],
        "story_id": ["zzz", "zzz"],
        "title": ["First", "Second"],
    })
    frames = {"matrix": matrix, "stories": stories}
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="story_id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        order={"sort_by": ["story_id"]},
        missing="empty",
    )
    result = out["result"]
    assert list(result["story_id"]) == ["s1", "s2"]
    assert list(result["title"]) == ["First", "Second"]


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_sort_by_lookup_key_rejected() -> None:
    """A temporary lookup sort field equal to the lookup key would leak it."""
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    with pytest.raises(ValueError, match="collides with the asymmetric lookup key"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["title"]},
            order={"sort_by": ["id"]},
            missing="empty",
        )


# ---------------------------------------------------------------------------
# Review 001 IMP-003: explicit asymmetric mode preserved even for equal names
# ---------------------------------------------------------------------------


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_equal_names_keeps_asymmetric_provenance() -> None:
    """source_key == lookup_key must still record the asymmetric shape."""
    matrix = pd.DataFrame({"id": ["s1", "s2"], "dynamic_1": ["a", "b"]})
    stories = pd.DataFrame({"id": ["s1", "s2"], "title": ["First", "Second"]})
    frames = {"matrix": matrix, "stories": stories}
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        missing="empty",
    )

    prov = out["_meta"]["derived"]["sheets"]["result"]["enrich_lookup"]
    assert prov == {
        "lookup": "stories",
        "source_key": "id",
        "lookup_key": "id",
        "helper_columns": ["title"],
    }
    assert "on" not in prov
    assert list(out["result"]["title"]) == ["First", "Second"]


@pytestmark_asymmetric
def test_enrich_lookup_asymmetric_pair_ignores_policy_key_applies_non_key_settings() -> None:
    """An explicit asymmetric pair owns key selection and ignores a conflicting
    helper-policy ``key``, but still consumes the policy's non-key settings."""
    frames = {
        "matrix": _matrix_story(),
        "stories": _stories(),
        "_meta": {
            "helper_policies": {
                "lookup": {
                    "stories": {
                        # Conflicting/irrelevant key is ignored in asymmetric mode.
                        "key": "some_other_key",
                        # Non-key settings are still applied.
                        "allowed_helpers": ["title"],
                        "default_helpers": ["title"],
                        "missing": "empty",
                    }
                }
            }
        },
    }
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="story_id",
        lookup_key="id",
        helpers="default",  # resolved from the policy's non-key default_helpers
    )
    result = out["result"]
    assert list(result["title"]) == ["First", "Second"]
    assert "id" not in result.columns
    prov = out["_meta"]["derived"]["sheets"]["result"]["enrich_lookup"]
    assert prov["source_key"] == "story_id"
    assert prov["lookup_key"] == "id"
    assert prov["helper_columns"] == ["title"]


# ---------------------------------------------------------------------------
# Review 002 R002-IMP-001: equal-name asymmetric helper collision safety
# ---------------------------------------------------------------------------


def _matrix_id() -> pd.DataFrame:
    """Source keyed by ``id`` (equal-name explicit asymmetric scenario)."""
    return pd.DataFrame({
        "id": ["s1", "s2"],
        "dynamic_1": ["a", "b"],
    })


def _stories_id() -> pd.DataFrame:
    return pd.DataFrame({
        "id": ["s1", "s2"],
        "title": ["First", "Second"],
    })


@pytestmark_asymmetric
def test_enrich_lookup_equal_name_helper_equals_key_rejected_values() -> None:
    frames = {"matrix": _matrix_id(), "stories": _stories_id()}
    with pytest.raises(ValueError, match="authoritative source key"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="id",
            lookup_key="id",
            helpers={"fields": ["id"]},
            missing="empty",
        )
    # No output/provenance produced; caller frames unchanged.
    assert "result" not in frames
    assert "_meta" not in frames


@pytestmark_asymmetric
def test_enrich_lookup_equal_name_mixed_helper_list_fails_atomically() -> None:
    frames = {"matrix": _matrix_id(), "stories": _stories_id()}
    with pytest.raises(ValueError, match="authoritative source key"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="id",
            lookup_key="id",
            helpers={"fields": ["id", "title"]},  # mixed list must fail atomically
            missing="empty",
        )
    assert "result" not in frames


@pytestmark_asymmetric
def test_enrich_lookup_equal_name_policy_default_helper_equals_key_rejected() -> None:
    frames = {
        "matrix": _matrix_id(),
        "stories": _stories_id(),
        "_meta": {
            "helper_policies": {
                "lookup": {
                    "stories": {"default_helpers": ["id"]},
                }
            }
        },
    }
    with pytest.raises(ValueError, match="authoritative source key"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="id",
            lookup_key="id",
            helpers="default",  # policy-derived helper equal to the key
        )
    assert "result" not in frames
    assert "derived" not in frames.get("_meta", {})


@pytestmark_asymmetric
def test_enrich_lookup_equal_name_sort_by_key_with_title_helper_succeeds() -> None:
    """sort_by on the (equal) key sorts the output key; it is not a helper."""
    matrix = pd.DataFrame({"id": ["s2", "s1"], "dynamic_1": ["b", "a"]})
    frames = {"matrix": matrix, "stories": _stories_id()}
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        order={"sort_by": ["id"]},
        missing="empty",
    )
    result = out["result"]
    assert list(result["id"]) == ["s1", "s2"]
    assert list(result["title"]) == ["First", "Second"]
    # Source key preserved as authoritative values, not overwritten.
    assert "title" in result.columns


@pytestmark_asymmetric
def test_enrich_lookup_equal_name_normal_helper_still_works() -> None:
    frames = {"matrix": _matrix_id(), "stories": _stories_id()}
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        missing="empty",
    )
    assert list(out["result"]["title"]) == ["First", "Second"]


def test_enrich_lookup_symmetric_helper_equals_key_unchanged_legacy() -> None:
    """Legacy symmetric behaviour is NOT tightened: helper == key does not raise."""
    frames = {"matrix": _matrix_id(), "stories": _stories_id()}
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        key="id",
        helpers={"fields": ["id"]},
        missing="empty",
    )
    # Symmetric mode still accepts this (unchanged); the key remains present.
    assert list(out["result"]["id"]) == ["s1", "s2"]


# ---------------------------------------------------------------------------
# Review 002 R002-IMP-003: duplicate helper requests
# ---------------------------------------------------------------------------


@pytestmark_asymmetric
def test_enrich_lookup_duplicate_helper_values_default_rejected() -> None:
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    with pytest.raises(ValueError, match="Duplicate helper field"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["title", "title"]},
            missing="empty",
        )
    assert "result" not in frames


@pytestmark_asymmetric
def test_enrich_lookup_duplicate_helper_values_before_key_rejected() -> None:
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    with pytest.raises(ValueError, match="Duplicate helper field"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["title", "title"]},
            order={"helper_position": "before_key"},
            missing="empty",
        )
    assert "result" not in frames


@pytestmark_asymmetric
def test_enrich_lookup_duplicate_policy_default_helpers_rejected() -> None:
    frames = {
        "matrix": _matrix_story(),
        "stories": _stories(),
        "_meta": {
            "helper_policies": {
                "lookup": {"stories": {"default_helpers": ["title", "title"]}}
            }
        },
    }
    with pytest.raises(ValueError, match="Duplicate helper field"):
        enrich_lookup(
            frames,
            source="matrix",
            lookup="stories",
            output="result",
            source_key="story_id",
            lookup_key="id",
            helpers="default",
        )
    assert "result" not in frames
    assert "derived" not in frames.get("_meta", {})


@pytestmark_asymmetric
def test_enrich_lookup_helper_also_used_as_sort_by_is_valid() -> None:
    """A single helper that is also the sort key is not a duplicate helper."""
    frames = {"matrix": _matrix_story(), "stories": _stories()}
    out = enrich_lookup(
        frames,
        source="matrix",
        lookup="stories",
        output="result",
        source_key="story_id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        order={"sort_by": ["title"]},
        missing="empty",
    )
    result = out["result"]
    # Sorted by title; helper present exactly once; provenance lists it once.
    assert list(result["title"]) == ["First", "Second"]
    assert list(result.columns).count("title") == 1
    prov = out["_meta"]["derived"]["sheets"]["result"]["enrich_lookup"]
    assert prov["helper_columns"] == ["title"]


def test_enrich_lookup_duplicate_helper_symmetric_also_rejected() -> None:
    """The duplicate-helper guard is generic: symmetric duplicates also fail.

    The same duplicate-label/duplicate-provenance defect existed in symmetric
    mode via the retained ``fields`` list; rejecting literal duplicates is a
    safe, backward-compatible tightening.
    """
    frames = _frames()
    with pytest.raises(ValueError, match="Duplicate helper field"):
        enrich_lookup(
            frames,
            source="variable_usage_matrix_raw",
            lookup="variables",
            output="result",
            on="ID",
            helpers={"fields": ["value_label_de", "value_label_de"]},
        )
