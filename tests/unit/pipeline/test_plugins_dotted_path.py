import sys
import textwrap
import importlib
from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.pipeline.registry import build_steps_from_config, run_pipeline

pytestmark = pytest.mark.ftr("FTR-TEST-HARNESS")


def test_dotted_path_step(tmp_path: Path, monkeypatch):
    # 1) Write a tiny module to disk.
    moddir = tmp_path / "extsteps"
    moddir.mkdir()
    (moddir / "__init__.py").write_text("", encoding="utf-8")
    (moddir / "steps.py").write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass
            from typing import Any, Dict
            import pandas as pd

            # minimal BoundStep-compatible factory
            def make_keep_columns_step(*, table: str, columns: list[str], name: str = "keep_columns"):
                from spreadsheet_handling.pipeline.types import BoundStep
                Frames = dict[str, pd.DataFrame]
                cfg = {"table": table, "columns": columns}

                def run(frames: Frames) -> Frames:
                    df = frames.get(table)
                    if df is None:
                        return frames
                    out = dict(frames)
                    keep = [c for c in columns if c in df.columns]
                    out[table] = df.loc[:, keep]
                    return out

                return BoundStep(name=name, config=cfg, fn=run)
            """
        ),
        encoding="utf-8",
    )

    # 2) Add the import path and import the module.
    sys.path.insert(0, str(tmp_path))
    try:
        importlib.import_module("extsteps.steps")  # sanity

        # 3) Build the pipeline from a dotted path.
        cfg = [
            {"step": "extsteps.steps:make_keep_columns_step", "table": "A", "columns": ["id", "name"]}
        ]
        steps = build_steps_from_config(cfg)

        frames = {"A": pd.DataFrame({"id": [1, 2], "name": ["x", "y"], "dropme": [0, 0]})}
        out = run_pipeline(frames, steps)

        assert set(out["A"].columns) == {"id", "name"}  # external transform applied
        assert "dropme" not in out["A"].columns
    finally:
        # Clean up.
        sys.path = [p for p in sys.path if p != str(tmp_path)]
