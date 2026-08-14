"""Invocation-boundary tests for the domain ingress coordinator.

Proves that ingress runs automatically at the three maintained external-meta
boundaries (orchestrator load, ``bootstrap_meta`` post-merge,
``apply_overrides`` post-merge), that list form never reaches persistence, and
that an ingress failure aborts before the saver runs.
See FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5.

The Phase-E E3 section at the bottom of this module proves the same three
boundaries abort atomically for a *metadata substrate* violation (not just a
Legend Blocks shape violation) -- i.e. every rule in ``INGRESS_RULES``, not
only the first one, is reached and enforced at every maintained call site.
See FTR-TRUSTED-INGRESS-P4A.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.domain.ingress.metadata_admission import (
    MetadataSubstrateAdmissionError,
)
from spreadsheet_handling.domain.meta_bootstrap import bootstrap_meta
from spreadsheet_handling.domain.yaml_overrides import apply_overrides
from spreadsheet_handling.pipeline.build import build_steps_from_config

pytestmark = [
    pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5"),
    pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A"),
]


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


def test_orchestrate_load_canonicalizes_null_before_structured_persistence(
    tmp_path: Path,
):
    in_dir, out_dir = tmp_path / "in", tmp_path / "out"
    _write_json_dir(
        in_dir,
        {"product": [{"id": "P-1"}]},
        meta={"legend_blocks": None},
    )

    frames = orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "json_dir", "path": str(out_dir)},
    )

    assert frames["_meta"]["legend_blocks"] == {}
    assert _read_out_meta(out_dir)["legend_blocks"] == {}


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


def test_bootstrap_meta_failure_leaves_complete_caller_graph_unchanged():
    frames = {
        "_meta": {
            "legend_blocks": {"kept": {"entries": [{"token": "K"}]}},
            "sheets": {"Data": {"options": {"freeze_header": False}}},
        }
    }
    before = copy.deepcopy(frames)
    meta = frames["_meta"]
    sheets = meta["sheets"]
    sheet_meta = sheets["Data"]
    options = sheet_meta["options"]

    with pytest.raises(ValueError):
        bootstrap_meta(
            frames,
            cli_overrides={"legend_blocks": [{"name": "d"}, {"name": "d"}]},
        )

    assert frames == before
    assert frames["_meta"] is meta
    assert frames["_meta"]["sheets"] is sheets
    assert frames["_meta"]["sheets"]["Data"] is sheet_meta
    assert frames["_meta"]["sheets"]["Data"]["options"] is options


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


def test_apply_overrides_failure_leaves_complete_caller_graph_unchanged():
    frames = {
        "_meta": {
            "legend_blocks": {"kept": {"entries": [{"token": "K"}]}},
            "sheets": {
                "Data": {
                    "freeze_header": False,
                    "options": {"column_widths": {"A": 12}},
                }
            },
        }
    }
    before = copy.deepcopy(frames)
    meta = frames["_meta"]
    sheets = meta["sheets"]
    sheet_meta = sheets["Data"]
    options = sheet_meta["options"]
    column_widths = options["column_widths"]

    with pytest.raises(ValueError, match="duplicate legend block identity"):
        apply_overrides(
            frames,
            {
                "defaults": {
                    "legend_blocks": [{"name": "dup"}, {"name": "dup"}],
                },
                "sheets": {
                    "Data": {
                        "freeze_header": True,
                        "options": {"column_widths": {"B": 20}},
                    }
                },
            },
        )

    assert frames == before
    assert frames["_meta"] is meta
    assert frames["_meta"]["sheets"] is sheets
    assert frames["_meta"]["sheets"]["Data"] is sheet_meta
    assert frames["_meta"]["sheets"]["Data"]["options"] is options
    assert frames["_meta"]["sheets"]["Data"]["options"]["column_widths"] is column_widths


def test_apply_overrides_success_preserves_merge_precedence_and_nested_values():
    frames = {
        "_meta": {
            "auto_filter": False,
            "sheets": {
                "Data": {
                    "freeze_header": False,
                    "options": {"column_widths": {"A": 12}},
                },
                "Untouched": {"freeze_header": True},
            },
        }
    }

    apply_overrides(
        frames,
        {
            "defaults": {"auto_filter": True, "freeze_header": False},
            "sheets": {
                "Data": {
                    "freeze_header": True,
                    "options": {"column_widths": {"B": 20}},
                }
            },
        },
    )

    assert frames["_meta"]["auto_filter"] is True
    assert frames["_meta"]["freeze_header"] is False
    assert frames["_meta"]["sheets"]["Data"] == {
        "freeze_header": True,
        "options": {"column_widths": {"A": 12, "B": 20}},
    }
    assert frames["_meta"]["sheets"]["Untouched"] == {"freeze_header": True}


def test_apply_overrides_ingress_failure_suppresses_saver(tmp_path: Path):
    in_dir, out_dir = tmp_path / "in", tmp_path / "out"
    _write_json_dir(
        in_dir,
        {"Data": [{"id": "D-1"}]},
        meta={
            "legend_blocks": {"kept": {"entries": [{"token": "K"}]}},
            "sheets": {"Data": {"freeze_header": False}},
        },
    )
    steps = build_steps_from_config(
        [
            {
                "step": "apply_overrides",
                "overrides": {
                    "defaults": {
                        "legend_blocks": [{"name": "dup"}, {"name": "dup"}],
                    },
                    "sheets": {"Data": {"freeze_header": True}},
                },
            }
        ]
    )

    with pytest.raises(ValueError, match="duplicate legend block identity"):
        orchestrate(
            input={"kind": "json_dir", "path": str(in_dir)},
            output={"kind": "json_dir", "path": str(out_dir)},
            steps=steps,
        )

    assert not out_dir.exists()


# ===========================================================================
# Phase-E E3: metadata substrate violation at every boundary (not just
# Legend Blocks shape). Proves ``metadata_substrate`` -- the second
# ``INGRESS_RULES`` entry -- is actually reached and enforced, and aborts
# atomically, at all three maintained call sites. See FTR-TRUSTED-INGRESS-P4A.
# ===========================================================================


def test_orchestrate_load_metadata_substrate_failure_suppresses_saver(tmp_path: Path):
    in_dir, out_dir = tmp_path / "in", tmp_path / "out"
    in_dir.mkdir()
    (in_dir / "products.yml").write_text("- id: 1\n", encoding="utf-8")
    # Reserved YAML metadata sidecar (Option A) carrying a non-str key --
    # loads fine at the backend boundary (mapping-shaped), then E3 rejects it.
    (in_dir / "_meta.yaml").write_text("1: x\n", encoding="utf-8")

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        orchestrate(
            input={"kind": "yaml_dir", "path": str(in_dir)},
            output={"kind": "json_dir", "path": str(out_dir)},
        )

    assert excinfo.value.kind == "unsupported_metadata_key"
    assert not out_dir.exists()


def test_bootstrap_meta_metadata_substrate_failure_leaves_complete_caller_graph_unchanged():
    frames = {
        "_meta": {
            "legend_blocks": {"kept": {"entries": [{"token": "K"}]}},
        }
    }
    before = copy.deepcopy(frames)
    meta = frames["_meta"]
    legend_blocks = meta["legend_blocks"]

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        bootstrap_meta(frames, cli_overrides={"bad": (1, 2)})

    assert excinfo.value.kind == "invalid_metadata_node"
    assert frames == before
    assert frames["_meta"] is meta
    assert frames["_meta"]["legend_blocks"] is legend_blocks


def test_apply_overrides_metadata_substrate_failure_leaves_complete_caller_graph_unchanged():
    frames = {
        "_meta": {
            "legend_blocks": {"kept": {"entries": [{"token": "K"}]}},
        }
    }
    before = copy.deepcopy(frames)
    meta = frames["_meta"]
    legend_blocks = meta["legend_blocks"]

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        apply_overrides(frames, {"defaults": {"bad": {1, 2}}})

    assert excinfo.value.kind == "invalid_metadata_node"
    assert frames == before
    assert frames["_meta"] is meta
    assert frames["_meta"]["legend_blocks"] is legend_blocks
