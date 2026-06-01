"""Invocation-boundary tests for the domain ingress coordinator.

Proves that ingress runs automatically at the three maintained external-meta
boundaries (orchestrator load, ``bootstrap_meta`` post-merge,
``apply_overrides`` post-merge), that list form never reaches persistence, and
that an ingress failure aborts before the saver runs.
See FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.domain.meta_bootstrap import bootstrap_meta
from spreadsheet_handling.domain.yaml_overrides import apply_overrides

pytestmark = pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5")


def _write_json_dir(path: Path, records: dict, meta: dict | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, rows in records.items():
        (path / f"{name}.json").write_text(json.dumps(rows), encoding="utf-8")
    if meta is not None:
        (path / "_meta.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")


def _read_out_meta(out_dir: Path) -> dict:
    return yaml.safe_load((out_dir / "_meta.yaml").read_text(encoding="utf-8"))


# --- orchestrator load boundary --------------------------------------------


def test_orchestrate_load_normalizes_list_form_before_persistence(tmp_path: Path):
    in_dir, out_dir = tmp_path / "in", tmp_path / "out"
    _write_json_dir(
        in_dir,
        {"product": [{"id": "P-1", "status": "A"}]},
        meta={
            "legend_blocks": [
                {
                    "name": "status_codes",
                    "title": "Status",
                    "entries": [{"token": "A", "label": "Active"}],
                    "resolved": {"top": 1, "left": 5},  # stale Resolution
                }
            ]
        },
    )

    frames = orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "json_dir", "path": str(out_dir)},
    )

    # Returned frames already carry canonical mapping form.
    blocks = frames["_meta"]["legend_blocks"]
    assert set(blocks) == {"status_codes"}
    assert "resolved" not in blocks["status_codes"]

    # Persisted structured sidecar is mapping form and never carries resolved.
    persisted = _read_out_meta(out_dir)["legend_blocks"]
    assert isinstance(persisted, dict)
    assert set(persisted) == {"status_codes"}
    assert "resolved" not in persisted["status_codes"]
    assert persisted["status_codes"]["entries"] == [{"token": "A", "label": "Active"}]


def test_orchestrate_ingress_failure_suppresses_saver(tmp_path: Path):
    in_dir, out_dir = tmp_path / "in", tmp_path / "out"
    _write_json_dir(
        in_dir,
        {"product": [{"id": "P-1"}]},
        meta={"legend_blocks": [{"name": "dup"}, {"name": "dup"}]},
    )

    with pytest.raises(ValueError, match="duplicate legend block identity"):
        orchestrate(
            input={"kind": "json_dir", "path": str(in_dir)},
            output={"kind": "json_dir", "path": str(out_dir)},
        )

    # Atomicity: no output produced when ingress fails before the saver.
    assert not out_dir.exists()


# --- bootstrap_meta boundary -----------------------------------------------


def test_bootstrap_meta_cannot_expose_list_form_from_cli_overrides():
    frames = {"_meta": {}}
    bootstrap_meta(
        frames,
        cli_overrides={
            "legend_blocks": [{"name": "z", "entries": [{"token": "Z"}]}]
        },
    )
    blocks = frames["_meta"]["legend_blocks"]
    assert isinstance(blocks, dict)
    assert set(blocks) == {"z"}


def test_bootstrap_meta_normalizes_list_form_from_profile_defaults():
    frames = {"_meta": {}}
    bootstrap_meta(
        frames,
        profile_defaults={
            "legend_blocks": [{"id": "p", "entries": [{"token": "P"}], "resolved": {}}]
        },
    )
    blocks = frames["_meta"]["legend_blocks"]
    assert set(blocks) == {"p"}
    assert "resolved" not in blocks["p"]


def test_bootstrap_meta_failure_does_not_write_list_form_back():
    frames = {"_meta": {"legend_blocks": {"kept": {"entries": [{"token": "K"}]}}}}
    with pytest.raises(ValueError):
        bootstrap_meta(
            frames,
            cli_overrides={"legend_blocks": [{"name": "d"}, {"name": "d"}]},
        )
    # Atomic: caller frames unchanged (canonical mapping form retained).
    assert frames["_meta"]["legend_blocks"] == {"kept": {"entries": [{"token": "K"}]}}


# --- apply_overrides boundary ----------------------------------------------


def test_apply_overrides_cannot_expose_list_form_from_defaults():
    frames = {"_meta": {}}
    apply_overrides(
        frames,
        {"defaults": {"legend_blocks": [{"name": "d", "entries": [{"token": "D"}]}]}},
    )
    blocks = frames["_meta"]["legend_blocks"]
    assert isinstance(blocks, dict)
    assert set(blocks) == {"d"}


def test_apply_overrides_strips_resolved_from_mapping_form():
    frames = {
        "_meta": {"legend_blocks": {"m": {"entries": [{"token": "M"}], "resolved": {}}}}
    }
    apply_overrides(frames, {})
    assert "resolved" not in frames["_meta"]["legend_blocks"]["m"]
