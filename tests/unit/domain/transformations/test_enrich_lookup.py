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

def test_enrich_lookup_writes_provenance() -> None:
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
