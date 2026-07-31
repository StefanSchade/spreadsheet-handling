"""Public build/run smoke for the axis/grouped composites (closes Slice 2 F-1).

GX-2 of ``FTR-XREF-AXIS-MAPPINGS-P4A2``. These drive the steps through the public
``build_steps_from_config`` + ``run_pipeline`` surface (not direct Python calls),
covering the GX-2 grouped composites and the Slice 2 flat axis steps. They also
pin the builder's ``name`` handling: the config ``name`` becomes the *step* name
and is not forwarded to the target function as an unexpected argument, so the
function's XRef ``config_id`` falls back to the relation/output frame name.
"""
from __future__ import annotations

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
            },
            {
                "step": "expand_grouped_xref",
                "matrix": "mtx",
                "output": "rel_out",
                "row_keys": ["row_id"],
                "source_frame": "src",
                "key_column": "key",
                "label_columns": ["grp", "leaf"],
            },
        ]
    )

    # The config ``name`` is consumed by the builder as the step name; it is not
    # forwarded to the target function as an unexpected argument.
    assert steps[0].name == "grouped_axis"

    frames = {"rel": _dense_relation(), "src": _source()}
    out = run_pipeline(frames, steps)

    # Dense relation is reproduced exactly through the public surface.
    pd.testing.assert_frame_equal(_sorted(out["rel_out"]), _sorted(_dense_relation()))
    # The intermediate grouped matrix is the trusted carrier, not a bare frame.
    assert isinstance(out["mtx"], GroupedMatrix)
    # ``name`` was not forwarded to the function, so the XRef config_id fell back
    # to the relation frame name -- metadata stays XRef-owned with public names.
    assert set(out["_meta"]["xref_crosstable"]) >= {"rel"}
    assert "grouped_xref" not in out["_meta"]


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
