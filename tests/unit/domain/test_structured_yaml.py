from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from spreadsheet_handling.domain.structured_yaml import write_structured_yaml
from spreadsheet_handling.pipeline.pipeline import (
    REGISTRY,
    StepRegistration,
    build_steps_from_config,
    run_pipeline,
)

pytestmark = pytest.mark.ftr("FTR-STRUCTURED-YAML-WRITER-P4")


def test_structured_yaml_pipeline_writes_mapping_and_grouped_sequence(tmp_path: Path) -> None:
    frames = {
        "variables": pd.DataFrame(
            [
                {
                    "variable_id": "var.term",
                    "value_label_de": "Laufzeit",
                    "data_type": "integer",
                    "business_component": "loan",
                },
                {
                    "variable_id": "var.amount",
                    "value_label_de": "Kreditbetrag",
                    "data_type": "number",
                    "business_component": "",
                },
            ]
        ),
        "request_mappings": pd.DataFrame(
            [
                {
                    "transaction_type_id": "create-loan",
                    "sort_key": 20,
                    "source_path": "request.loan.term",
                    "target_field": "laufzeit",
                    "variable_id": "var.term",
                },
                {
                    "transaction_type_id": "create-loan",
                    "sort_key": 10,
                    "source_path": "request.loan.amount",
                    "target_field": "kreditbetrag",
                    "variable_id": "var.amount",
                },
            ]
        ),
    }
    output_dir = tmp_path / "nxt-config-generated"

    steps = build_steps_from_config(
        [
            {
                "step": "write_structured_yaml",
                "output_dir": str(output_dir),
                "files": [
                    {
                        "path": "variable/variable-registry.yml",
                        "frame": "variables",
                        "root": "mapping",
                        "key": "variable_id",
                        "value": {
                            "label": "value_label_de",
                            "type": "data_type",
                            "businessComponent": "business_component",
                        },
                        "omit_empty": ["businessComponent"],
                    },
                    {
                        "path": "calculation/mappings/request-mappings.yml",
                        "frame": "request_mappings",
                        "root": "mapping",
                        "key": "transaction_type_id",
                        "sequence": {
                            "sort_by": ["sort_key"],
                            "value": {
                                "source": "source_path",
                                "target.nominaldaten.field": "target_field",
                                "variable": "variable_id",
                            },
                        },
                    },
                ],
            }
        ]
    )

    out = run_pipeline(frames, steps)
    first_registry = (output_dir / "variable" / "variable-registry.yml").read_text(encoding="utf-8")
    first_request = (output_dir / "calculation" / "mappings" / "request-mappings.yml").read_text(
        encoding="utf-8"
    )
    run_pipeline(frames, steps)

    assert isinstance(REGISTRY["write_structured_yaml"], StepRegistration)
    assert steps[0].config["target"].endswith(":write_structured_yaml")
    assert first_registry == (output_dir / "variable" / "variable-registry.yml").read_text(
        encoding="utf-8"
    )
    assert first_request == (
        output_dir / "calculation" / "mappings" / "request-mappings.yml"
    ).read_text(encoding="utf-8")

    assert yaml.safe_load(first_registry) == {
        "var.amount": {"label": "Kreditbetrag", "type": "number"},
        "var.term": {"label": "Laufzeit", "type": "integer", "businessComponent": "loan"},
    }
    assert yaml.safe_load(first_request) == {
        "create-loan": [
            {
                "source": "request.loan.amount",
                "target": {"nominaldaten": {"field": "kreditbetrag"}},
                "variable": "var.amount",
            },
            {
                "source": "request.loan.term",
                "target": {"nominaldaten": {"field": "laufzeit"}},
                "variable": "var.term",
            },
        ]
    }
    assert out["structured_yaml_files"]["path"].tolist() == [
        "variable/variable-registry.yml",
        "calculation/mappings/request-mappings.yml",
    ]


def test_structured_yaml_writer_supports_list_root(tmp_path: Path) -> None:
    frames = {
        "operations": pd.DataFrame(
            [
                {"operation_id": "op-b", "sort_key": 2, "endpoint": "/b", "method": "POST"},
                {"operation_id": "op-a", "sort_key": 1, "endpoint": "/a", "method": "GET"},
            ]
        )
    }

    write_structured_yaml(
        frames,
        output_dir=tmp_path,
        files=[
            {
                "path": "calculation/calculation-operations.yml",
                "frame": "operations",
                "root": "list",
                "sort_by": ["sort_key"],
                "value": {
                    "id": "operation_id",
                    "request.endpoint": "endpoint",
                    "request.method": "method",
                },
            }
        ],
    )

    assert yaml.safe_load(
        (tmp_path / "calculation" / "calculation-operations.yml").read_text()
    ) == [
        {"id": "op-a", "request": {"endpoint": "/a", "method": "GET"}},
        {"id": "op-b", "request": {"endpoint": "/b", "method": "POST"}},
    ]


def test_structured_yaml_writer_sorts_numeric_keys_numerically(tmp_path: Path) -> None:
    frames = {
        "operations": pd.DataFrame(
            [
                {"operation_id": "op-10", "sort_key": 10},
                {"operation_id": "op-2", "sort_key": 2},
                {"operation_id": "op-9", "sort_key": 9},
            ]
        )
    }

    write_structured_yaml(
        frames,
        output_dir=tmp_path,
        files=[
            {
                "path": "operations.yml",
                "frame": "operations",
                "root": "list",
                "sort_by": ["sort_key"],
                "value": {"id": "operation_id"},
            }
        ],
    )

    assert yaml.safe_load((tmp_path / "operations.yml").read_text()) == [
        {"id": "op-2"},
        {"id": "op-9"},
        {"id": "op-10"},
    ]


def test_structured_yaml_writer_supports_composite_keys(tmp_path: Path) -> None:
    frames = {
        "variables": pd.DataFrame(
            [
                {"component": "loan", "variable_id": "amount", "label": "Kreditbetrag"},
                {"component": "loan", "variable_id": "term", "label": "Laufzeit"},
            ]
        )
    }

    write_structured_yaml(
        frames,
        output_dir=tmp_path,
        files=[
            {
                "path": "variable/variable-registry.yml",
                "frame": "variables",
                "key": ["component", "variable_id"],
                "value": {"label": "label"},
            }
        ],
    )

    assert yaml.safe_load((tmp_path / "variable" / "variable-registry.yml").read_text()) == {
        "loan": {
            "amount": {"label": "Kreditbetrag"},
            "term": {"label": "Laufzeit"},
        }
    }


def test_structured_yaml_writer_rejects_duplicate_output_paths(tmp_path: Path) -> None:
    frames = {"variables": pd.DataFrame([{"variable_id": "v1", "label": "Variable"}])}

    with pytest.raises(ValueError, match="duplicates previous file path"):
        write_structured_yaml(
            frames,
            output_dir=tmp_path,
            files=[
                {
                    "path": "variable/variable-registry.yml",
                    "frame": "variables",
                    "key": "variable_id",
                    "value": {"label": "label"},
                },
                {
                    "path": "variable/variable-registry.yml",
                    "frame": "variables",
                    "key": "variable_id",
                    "value": {"label": "label"},
                },
            ],
        )


def test_structured_yaml_writer_rejects_paths_escaping_output_dir(tmp_path: Path) -> None:
    frames = {"variables": pd.DataFrame([{"variable_id": "v1", "label": "Variable"}])}

    with pytest.raises(ValueError, match="escapes output_dir"):
        write_structured_yaml(
            frames,
            output_dir=tmp_path,
            files=[
                {
                    "path": "../escape.yml",
                    "frame": "variables",
                    "key": "variable_id",
                    "value": {"label": "label"},
                }
            ],
        )


def test_structured_yaml_writer_fails_on_missing_required_values(tmp_path: Path) -> None:
    frames = {"variables": pd.DataFrame([{"variable_id": "v1", "label": ""}])}

    with pytest.raises(ValueError, match="required field 'label'.*is empty"):
        write_structured_yaml(
            frames,
            output_dir=tmp_path,
            files=[
                {
                    "path": "variable/variable-registry.yml",
                    "frame": "variables",
                    "key": "variable_id",
                    "value": {"label": "label"},
                }
            ],
        )


def test_structured_yaml_writer_fails_on_missing_columns(tmp_path: Path) -> None:
    frames = {"variables": pd.DataFrame([{"variable_id": "v1"}])}

    with pytest.raises(KeyError, match="missing columns: \\['label'\\]"):
        write_structured_yaml(
            frames,
            output_dir=tmp_path,
            files=[
                {
                    "path": "variable/variable-registry.yml",
                    "frame": "variables",
                    "key": "variable_id",
                    "value": {"label": "label"},
                }
            ],
        )
