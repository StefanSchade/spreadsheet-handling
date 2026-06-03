"""Shared fixtures for the roundtrip test layer.

Roundtrip tests exercise the full canonical -> workbook -> canonical cycle
through the public CLI entry point (`spreadsheet_handling.cli.apps.run.main`).
They assert invariants over the cycle as a whole, not over individual steps.

This module owns:
* the synthetic dataset fixture (minimal FK dataset);
* a helper that runs the CLI entry function in-process with argv;
* generated forward and reverse pipeline YAMLs per test working directory.

Tests must not reach below the CLI entry into domain functions directly;
use unit or integration tests for that.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from spreadsheet_handling.cli.apps import run as runmod


_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "minimal_fk_dataset"


def _copy_canonical(target: Path) -> Path:
    """Copy the canonical seed data into the test working directory."""
    canonical = target / "canonical"
    canonical.mkdir(parents=True, exist_ok=True)
    for src in (_FIXTURE_ROOT / "canonical").glob("*.json"):
        shutil.copy(src, canonical / src.name)
    return canonical


def _forward_pipeline(canonical_dir: Path, sheet_path: Path) -> dict[str, Any]:
    """Build the canonical -> workbook pipeline config dict."""
    return {
        "io": {
            "input": {"kind": "json_dir", "path": str(canonical_dir)},
            "output": {"kind": "xlsx", "path": str(sheet_path)},
        },
        "pipeline": [
            {
                "step": "configure_fk_helpers",
                "targets": {
                    "entities": {
                        "key": "id",
                        "allowed_helpers": ["name"],
                        "default_helpers": ["name"],
                        "helper_prefix": "_",
                        "fk_column": "entity_id",
                    }
                },
            },
            {
                "step": "add_fk_helpers",
                "defaults": {"levels": 2, "helper_value_mode": "values"},
            },
            # Flatten the MultiIndex headers introduced by add_fk_helpers so
            # the workbook has plain string headers. Without this step the
            # parsed frame keeps the helper column as a tuple, and the JSON
            # backend's MultiIndex filter (drops columns whose first segment
            # starts with `_`) would mask the cleanup-contract invariant.
            {"step": "flatten_headers", "sheet": "items", "mode": "level0"},
            {
                "step": "configure_workbook_view",
                "sheets": [
                    {"frame": "items", "sheet": "items",
                     "helper_columns": ["_entities_name"]},
                    {"frame": "entities", "sheet": "entities"},
                ],
            },
        ],
    }


def _reverse_pipeline(sheet_path: Path, reimport_dir: Path) -> dict[str, Any]:
    """Build the workbook -> canonical pipeline config dict.

    The cleanup intent is declared (apply_derived_column_policy). Whether
    the cleanup is honored is the invariant under test.

    The forward pipeline already flattens MultiIndex headers, so the
    workbook carries plain string headers. The reverse pipeline therefore
    parses helper columns as ordinary string-headed columns -- the JSON
    backend's MultiIndex filter no longer hides the cleanup contract.
    Whether helpers reach canonical JSON is decided entirely by whether
    the declared cleanup step honors its intent.
    """
    return {
        "io": {
            "input": {"kind": "xlsx", "path": str(sheet_path)},
            "output": {"kind": "json_dir", "path": str(reimport_dir)},
        },
        "pipeline": [
            {
                "step": "apply_workbook_view_sheet_mappings",
                "logical_frames": ["items", "entities"],
            },
            {"step": "apply_derived_column_policy",
             "source": "items", "policy": "drop"},
        ],
    }


def _write_yaml(path: Path, content: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
    return path


def _run_cli(config_path: Path) -> int:
    """Invoke the public CLI entry function (same path as `sheets-run`).

    Roundtrip tests intentionally use this entry point instead of
    `orchestrate()` directly, so the CLI argv plumbing is exercised too.
    """
    return runmod.main(["--config", str(config_path)])


@pytest.fixture
def minimal_fk_workdir(tmp_path: Path):
    """Prepare a roundtrip working directory with helpers attached.

    Returns an object exposing:
    * `canonical` -- the seed canonical json_dir;
    * `reimport` -- the reimport target json_dir (created on demand);
    * `sheet` -- the spreadsheet file path used for the round trip;
    * `run_forward()` -- write the forward YAML and call the CLI;
    * `run_reverse()` -- write the reverse YAML and call the CLI;
    * `load_reimport(frame)` -- read a reimported frame as a list of dicts.
    """

    class _Workdir:
        def __init__(self, root: Path) -> None:
            self.root = root
            self.canonical = _copy_canonical(root)
            self.reimport = root / "reimport"
            self.sheet = root / "workbook.xlsx"
            self._forward_yaml = root / "forward.yaml"
            self._reverse_yaml = root / "reverse.yaml"

        def run_forward(self) -> int:
            _write_yaml(self._forward_yaml,
                        _forward_pipeline(self.canonical, self.sheet))
            return _run_cli(self._forward_yaml)

        def run_reverse(self) -> int:
            _write_yaml(self._reverse_yaml,
                        _reverse_pipeline(self.sheet, self.reimport))
            return _run_cli(self._reverse_yaml)

        def load_reimport(self, frame: str) -> list[dict[str, Any]]:
            path = self.reimport / f"{frame}.json"
            return json.loads(path.read_text(encoding="utf-8"))

    return _Workdir(tmp_path)
