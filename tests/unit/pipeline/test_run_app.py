from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.pipeline.config import AppConfig, IOConfig, IOEndpoint
from spreadsheet_handling.pipeline.runner import run_app


pytestmark = pytest.mark.ftr("FTR-REVIEW-001-BACKEND-DISPATCH-P4A-SLICE02")


def test_run_app_passes_input_header_levels(tmp_path: Path) -> None:
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    (in_dir / "products.csv").write_text("group,group\nid,name\n1,Alpha\n", encoding="utf-8")

    app = AppConfig(
        io=IOConfig(
            inputs={"primary": IOEndpoint(kind="csv_dir", path=str(in_dir), header_levels=2)},
            output=IOEndpoint(kind="json_dir", path=str(out_dir)),
        ),
    )

    frames, _meta, issues = run_app(app)

    assert not issues
    assert isinstance(frames["products"].columns, pd.MultiIndex)
    assert frames["products"].columns.nlevels == 2
    assert list(frames["products"].columns) == [("group", ""), ("group.1", "")]
    assert (out_dir / "products.json").exists()


def test_run_app_wraps_unknown_input_kind(tmp_path: Path) -> None:
    app = AppConfig(
        io=IOConfig(
            inputs={"primary": IOEndpoint(kind="bogus", path=str(tmp_path / "in"))},
            output=IOEndpoint(kind="json_dir", path=str(tmp_path / "out")),
        ),
    )

    with pytest.raises(ValueError, match="Unsupported input kind: 'bogus'"):
        run_app(app)


def test_run_app_wraps_unknown_output_kind(tmp_path: Path) -> None:
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    (in_dir / "products.json").write_text('[{"id": "1"}]', encoding="utf-8")
    app = AppConfig(
        io=IOConfig(
            inputs={"primary": IOEndpoint(kind="json_dir", path=str(in_dir))},
            output=IOEndpoint(kind="bogus", path=str(tmp_path / "out")),
        ),
    )

    with pytest.raises(ValueError, match="Unsupported output kind: 'bogus'"):
        run_app(app)
