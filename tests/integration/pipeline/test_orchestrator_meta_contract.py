from __future__ import annotations

import json
from pathlib import Path

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.pipeline.steps import make_add_validations_step


def _write_json_dir(path: Path, data: dict[str, list[dict]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, records in data.items():
        (path / f"{name}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def test_orchestrate_returns_meta_sidecar_after_generic_steps(tmp_path: Path) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    _write_json_dir(
        in_dir,
        {
            "product": [
                {"id": "P-1", "status": "active"},
                {"id": "P-2", "status": "pilot"},
            ]
        },
    )

    frames = orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "json_dir", "path": str(out_dir)},
        steps=[
            make_add_validations_step(
                rules=[
                    {
                        "sheet": "product",
                        "column": "status",
                        "rule": {"type": "in_list", "values": ["active", "pilot"]},
                    }
                ]
            )
        ],
    )

    assert "_meta" in frames
    assert isinstance(frames["_meta"], dict)
    assert frames["_meta"]["constraints"][0]["sheet"] == "product"
