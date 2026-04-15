from __future__ import annotations

import pandas as pd

from spreadsheet_handling.pipeline.registry import build_steps_from_config, run_pipeline


def test_pipeline_steps_preserve_meta_sidecar_and_skip_reserved_keys() -> None:
    frames = {
        "product": pd.DataFrame(
            {
                "id": ["P-1"],
                "name": ["Starter"],
                "id_(product_manager)": ["PM-1"],
                "status": ["active"],
            }
        ),
        "product_manager": pd.DataFrame(
            {
                "id": ["PM-1"],
                "name": ["Marta"],
            }
        ),
    }

    cfg_pipeline = [
        {
            "step": "add_validations",
            "rules": [
                {
                    "sheet": "product",
                    "column": "status",
                    "rule": {"type": "in_list", "values": ["active", "pilot"]},
                }
            ],
        },
        {
            "step": "validate",
            "mode_duplicate_ids": "warn",
            "mode_missing_fk": "warn",
            "defaults": {
                "id_field": "id",
                "label_field": "name",
                "detect_fk": True,
                "helper_prefix": "_",
            },
        },
        {
            "step": "apply_fks",
            "defaults": {
                "id_field": "id",
                "label_field": "name",
                "detect_fk": True,
                "helper_prefix": "_",
            },
        },
        {"step": "reorder_helpers", "helper_prefix": "_"},
        {"step": "flatten_headers", "mode": "level0"},
    ]

    steps = build_steps_from_config(cfg_pipeline)
    out = run_pipeline(frames, steps)

    assert "_meta" in out
    assert out["_meta"]["constraints"][0]["sheet"] == "product"
    assert "_product_manager_name" in out["product"].columns

    # FTR-FK-HELPER-PROVENANCE-CLEANUP: apply_fks writes derived provenance
    prov = out["_meta"]["derived"]["sheets"]["product"]["helper_columns"]
    assert len(prov) == 1
    assert prov[0]["column"] == "_product_manager_name"
    assert prov[0]["fk_column"] == "id_(product_manager)"
    assert prov[0]["target"] == "product_manager"
    assert prov[0]["value_field"] == "name"
