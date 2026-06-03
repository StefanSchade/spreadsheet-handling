"""Pipeline-level registration and integration tests for infer_fk_relations."""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.pipeline import (
    REGISTRY,
    build_steps_from_config,
    run_pipeline,
)
from spreadsheet_handling.pipeline.types import StepRegistration


pytestmark = pytest.mark.ftr("FTR-INFER-FK-RELATIONS-CONFIGURATION-STEP-P5")


def _frames() -> dict:
    return {
        "product": pd.DataFrame(
            {
                "id": ["p1", "p2"],
                "id_(product_manager)": ["m1", "m2"],
            }
        ),
        "product_manager": pd.DataFrame(
            {
                "id": ["m1", "m2"],
                "name": ["Alice", "Bob"],
            }
        ),
    }


def test_infer_fk_relations_registry_entry_is_configuration_step() -> None:
    entry = REGISTRY["infer_fk_relations"]
    assert isinstance(entry, StepRegistration)
    assert entry.target == "spreadsheet_handling.domain.fk_relations:infer_fk_relations"


def test_infer_fk_relations_runs_through_pipeline_and_writes_v2_policy() -> None:
    steps = build_steps_from_config(
        [
            {
                "step": "infer_fk_relations",
                "mode": "naming_convention",
                "id_columns": ["id"],
                "fk_patterns": ["id_({target})"],
                "target_label_fields": ["name", "label"],
                "on_ambiguous": "fail",
                "on_missing_target": "fail",
            }
        ]
    )
    out = run_pipeline(_frames(), steps)
    fk_root = out["_meta"]["helper_policies"]["fk"]
    assert fk_root["schema_version"] == 2
    assert len(fk_root["relations"]) == 1
    relation = fk_root["relations"][0]
    assert relation["produced_by"]["step"] == "infer_fk_relations"
    assert relation["produced_by"]["mode"] == "naming_convention"


def test_infer_fk_relations_then_configure_fk_helpers_compose_in_pipeline() -> None:
    frames = _frames()
    frames["supplier"] = pd.DataFrame({"id": ["sup1"], "name": ["SuppCo"]})
    frames["supplier_rel"] = pd.DataFrame(
        {"id": ["sr1"], "supplier_key": ["sup1"]}
    )
    steps = build_steps_from_config(
        [
            {"step": "infer_fk_relations"},
            {
                "step": "configure_fk_helpers",
                "targets": {
                    "supplier": {
                        "key": "id",
                        "allowed_helpers": ["name"],
                        "default_helpers": ["name"],
                        "fk_column": "supplier_key",
                    }
                },
            },
        ]
    )
    out = run_pipeline(frames, steps)
    relations = out["_meta"]["helper_policies"]["fk"]["relations"]
    by_key = {(r["source_frame"], r["source_column"]): r["produced_by"]["step"] for r in relations}
    assert by_key == {
        ("product", "id_(product_manager)"): "infer_fk_relations",
        ("supplier_rel", "supplier_key"): "configure_fk_helpers",
    }
