"""Public build/run smoke for the axis/grouped composites (closes Slice 2 F-1).

GX-2 of ``FTR-XREF-AXIS-MAPPINGS-P4A2``. These drive the steps through the public
``build_steps_from_config`` + ``run_pipeline`` surface (not direct Python calls),
covering the GX-2 grouped composites and the Slice 2 flat axis steps. They pin
the corrected vocabulary: config ``name`` is the pipeline step name, while
``xref_config_id`` reaches the grouped target and selects XRef metadata identity.
"""
from __future__ import annotations

import copy

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.grouped_xref import GroupedMatrix
from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution import run_pipeline

pytestmark = pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")

_KEYS = ("credit.annuity_loan", "credit.fixed_rate_loan", "deposit.balance")


def _dense_relation() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"row_id": rid, "column_key": key, "value": f"{rid}:{key}"}
            for rid in ("r1", "r2")
            for key in _KEYS
        ]
    )


def _source() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "key": list(_KEYS),
            "grp": ["Kredit", "Kredit", "Einlage"],
            "leaf": ["Annuitätendarlehen", "Festzinsdarlehen", "Guthaben"],
        }
    )


def _sorted(relation: pd.DataFrame) -> pd.DataFrame:
    return relation.sort_values(["row_id", "column_key"]).reset_index(drop=True)


def test_grouped_composites_roundtrip_through_public_build_and_run() -> None:
    steps = build_steps_from_config(
        [
            {
                "step": "contract_grouped_xref",
                "relation": "rel",
                "output": "mtx",
                "row_keys": ["row_id"],
                "source_frame": "src",
                "key_column": "key",
                "label_columns": ["grp", "leaf"],
                "name": "grouped_axis",
                "xref_config_id": "grouped_axis_config",
            },
            {
                "step": "expand_grouped_xref",
                "matrix": "mtx",
                "output": "rel_out",
                "row_keys": ["row_id"],
                "source_frame": "src",
                "key_column": "key",
                "label_columns": ["grp", "leaf"],
                "xref_config_id": "grouped_axis_inverse",
            },
        ]
    )

    # The config ``name`` is consumed by the builder as the step name, while the
    # explicit XRef ID remains in target configuration.
    assert steps[0].name == "grouped_axis"
    assert steps[0].config["xref_config_id"] == "grouped_axis_config"

    frames = {"rel": _dense_relation(), "src": _source()}
    out = run_pipeline(frames, steps)

    # Dense relation is reproduced exactly through the public surface.
    pd.testing.assert_frame_equal(_sorted(out["rel_out"]), _sorted(_dense_relation()))
    # The intermediate grouped matrix is the trusted carrier, not a bare frame.
    assert isinstance(out["mtx"], GroupedMatrix)
    # Both explicit IDs reached unchanged XRef; metadata stays XRef-owned.
    assert set(out["_meta"]["xref_crosstable"]) == {
        "grouped_axis_config",
        "grouped_axis_inverse",
    }
    assert "grouped_xref" not in out["_meta"]


def test_public_builder_xref_config_id_disambiguates_matching_metadata() -> None:
    forward_step = build_steps_from_config(
        [
            {
                "step": "contract_grouped_xref",
                "relation": "rel",
                "output": "mtx",
                "row_keys": ["row_id"],
                "source_frame": "src",
                "key_column": "key",
                "label_columns": ["grp", "leaf"],
                "xref_config_id": "seed",
            }
        ]
    )
    forward = run_pipeline({"rel": _dense_relation(), "src": _source()}, forward_step)
    payload = forward["_meta"]["xref_crosstable"]["seed"]
    ambiguous = dict(forward)
    ambiguous["_meta"] = copy.deepcopy(forward["_meta"])
    ambiguous["_meta"]["xref_crosstable"] = {
        "wanted": copy.deepcopy(payload),
        "other": copy.deepcopy(payload),
    }

    inverse_steps = build_steps_from_config(
        [
            {
                "step": "expand_grouped_xref",
                "name": "readable_inverse_step",
                "xref_config_id": "wanted",
                "matrix": "mtx",
                "output": "rel_out",
                "row_keys": ["row_id"],
                "source_frame": "src",
                "key_column": "key",
                "label_columns": ["grp", "leaf"],
            }
        ]
    )
    assert inverse_steps[0].name == "readable_inverse_step"
    assert inverse_steps[0].config["xref_config_id"] == "wanted"
    out = run_pipeline(ambiguous, inverse_steps)
    pd.testing.assert_frame_equal(_sorted(out["rel_out"]), _sorted(_dense_relation()))


def test_slice2_flat_axis_steps_roundtrip_through_public_build_and_run() -> None:
    steps = build_steps_from_config(
        [
            {
                "step": "project_axis_labels",
                "relation": "rel",
                "output": "labelled",
                "source_frame": "src",
                "key_column": "key",
                "label_column": "grp",
            },
            {
                "step": "restore_axis_keys",
                "relation": "labelled",
                "output": "restored",
                "source_frame": "src",
                "key_column": "key",
                "label_column": "grp",
            },
        ]
    )

    # Flat one-level source: canonical key -> a unique visible label.
    source = pd.DataFrame(
        {
            "key": ["credit.annuity_loan", "deposit.balance"],
            "grp": ["Kredit-Annuität", "Einlage-Guthaben"],
        }
    )
    relation = pd.DataFrame(
        {
            "row_id": ["r1", "r2"],
            "column_key": ["credit.annuity_loan", "deposit.balance"],
            "value": [1, 2],
        }
    )
    out = run_pipeline({"rel": relation, "src": source}, steps)

    # project then restore returns the canonical keys unchanged.
    pd.testing.assert_frame_equal(
        out["restored"].reset_index(drop=True), relation.reset_index(drop=True)
    )
