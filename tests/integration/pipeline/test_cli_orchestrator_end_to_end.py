"""Application orchestrator integration slice.

Exercises the public orchestrate() path with real JSON filesystem IO and a
pipeline step between load and save.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.pipeline.types import BoundStep, Frames


pytestmark = pytest.mark.ftr("FTR-ONE-ORCHESTRATOR")


def _write_json_dir(path: Path, data: dict[str, list[dict]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, records in data.items():
        (path / f"{name}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )


SAMPLE_DATA = {
    "products": [
        {"id": "a", "name": "Alpha"},
        {"id": "b", "name": "Bravo"},
    ]
}


def test_pack_json_to_json_via_orchestrate(tmp_path: Path) -> None:
    """End-to-end: sheets-pack-style call through the real orchestrate()."""
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    _write_json_dir(in_dir, SAMPLE_DATA)

    frames = orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "json_dir", "path": str(out_dir)},
    )

    assert "products" in frames
    assert len(frames["products"]) == 2
    assert (out_dir / "products.json").exists()


def test_orchestrate_with_step(tmp_path: Path) -> None:
    """Verify that steps are applied between load and save."""
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    _write_json_dir(in_dir, SAMPLE_DATA)

    def drop_name(frames: Frames) -> Frames:
        return {
            name: frame.drop(columns=["name"]) if isinstance(frame, pd.DataFrame) else frame
            for name, frame in frames.items()
        }

    step = BoundStep(name="drop_name", config={}, fn=drop_name)

    frames = orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "json_dir", "path": str(out_dir)},
        steps=[step],
    )

    assert list(frames["products"].columns) == ["id"]
    written = json.loads((out_dir / "products.json").read_text(encoding="utf-8"))
    assert "name" not in written[0]


@pytest.mark.ftr("FTR-ODS-CALC-ADAPTER-IMPLEMENTATION-P3J")
def test_orchestrate_supports_ods_backend_kind(tmp_path: Path) -> None:
    in_dir = tmp_path / "in"
    ods_path = tmp_path / "products.ods"
    out_dir = tmp_path / "out"
    _write_json_dir(in_dir, SAMPLE_DATA)

    orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "ods", "path": str(ods_path)},
    )

    assert ods_path.exists()

    frames = orchestrate(
        input={"kind": "ods", "path": str(ods_path)},
        output={"kind": "json_dir", "path": str(out_dir)},
    )

    assert frames["products"].to_dict(orient="records") == SAMPLE_DATA["products"]
    written = json.loads((out_dir / "products.json").read_text(encoding="utf-8"))
    assert written == SAMPLE_DATA["products"]


@pytest.mark.ftr("FTR-COMPACT-TRANSFORM-API-ERGONOMICS-P4")
def test_orchestrate_supports_calc_backend_alias(tmp_path: Path) -> None:
    in_dir = tmp_path / "in"
    calc_path = tmp_path / "products.ods"
    out_dir = tmp_path / "out"
    _write_json_dir(in_dir, SAMPLE_DATA)

    orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "calc", "path": str(calc_path)},
    )

    assert calc_path.exists()

    frames = orchestrate(
        input={"kind": "calc", "path": str(calc_path)},
        output={"kind": "json_dir", "path": str(out_dir)},
    )

    assert frames["products"].to_dict(orient="records") == SAMPLE_DATA["products"]
