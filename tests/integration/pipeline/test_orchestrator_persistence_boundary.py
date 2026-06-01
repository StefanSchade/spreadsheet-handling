"""End-to-end coverage for the orchestrator-owned persistence boundary.

Verifies that ``orchestrate()`` applies the meta projection *before*
``_save_frames`` runs, that the projection is carrier-neutral (i.e. it also
runs for spreadsheet outputs), and that a Dino-shaped repeated-run
contamination is broken at the write side: an input containing the
runtime-produced FK-helper v2 relation that historically caused
``Frame 'groups' must have flat columns`` does not survive into the
persisted sidecar after a clean pipeline run.

No real Dino data is committed; the contamination shape is synthesised from
the public registry contract.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.io_backends.json_backend import write_json_dir
from spreadsheet_handling.pipeline.steps import make_identity_step


pytestmark = pytest.mark.ftr("BUG-RUNTIME-META-PERSISTENCE-BOUNDARY-P4A")


def _write_input_dir(tmp_path: Path, meta: dict) -> Path:
    """Build a json_dir input with a minimal frame and the given _meta."""
    in_dir = tmp_path / "in"
    frames = {
        "groups": pd.DataFrame({"id": ["g1"], "home_place_id": ["p1"]}),
        "_meta": meta,
    }
    write_json_dir(frames, in_dir)
    return in_dir


def _runtime_relation(source: str, target: str = "places") -> dict:
    return {
        "source_frame": source,
        "source_column": "home_place_id",
        "target_frame": target,
        "target_key": "id",
        "helper_columns": [{"column": "_places_name", "target_field": "name"}],
        "helper_fields": ["name"],
        "helper_prefix": "_",
        "produced_by": {"mode": "explicit", "step": "configure_fk_helpers"},
    }


def test_json_dir_output_drops_runtime_produced_relations(tmp_path: Path) -> None:
    """Strukturelle Persistenz ruft die Meta-Projektion vor dem Schreiben auf."""
    meta = {
        "version": "1.0",
        "freeze_header": True,
        "helper_policies": {
            "fk": {
                "schema_version": 2,
                "relations": [_runtime_relation("groups")],
                "places": {"target": "places", "fk_column": "home_place_id"},
            },
        },
        "derived": {"sheets": {"groups": {"helper_columns": []}}},
    }
    in_dir = _write_input_dir(tmp_path, meta)
    out_dir = tmp_path / "out"

    orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "json_dir", "path": str(out_dir)},
        steps=[make_identity_step()],
    )

    persisted = yaml.safe_load((out_dir / "_meta.yaml").read_text(encoding="utf-8"))
    assert "derived" not in persisted
    fk = persisted["helper_policies"]["fk"]
    assert "relations" not in fk, "runtime-produced relation must not survive persistence"
    assert "schema_version" not in fk, "empty relations envelope removed with its schema_version"
    assert fk["places"]["target"] == "places", "v1 per-target entry preserved"
    assert persisted["version"] == "1.0"
    assert persisted["freeze_header"] is True


def test_orchestrator_returns_projected_meta_in_memory(tmp_path: Path) -> None:
    """The boundary applies to the returned frames too: in-process callers
    of ``orchestrate()`` see the persistable view, not the runtime view."""
    in_dir = _write_input_dir(
        tmp_path,
        {
            "derived": {"x": 1},
            "helper_policies": {
                "fk": {
                    "schema_version": 2,
                    "relations": [_runtime_relation("groups")],
                },
            },
        },
    )
    out_dir = tmp_path / "out"

    result = orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "json_dir", "path": str(out_dir)},
        steps=[make_identity_step()],
    )
    meta = result["_meta"]
    assert "derived" not in meta
    assert "relations" not in meta["helper_policies"]["fk"]


def test_persistence_boundary_runs_for_spreadsheet_output(tmp_path: Path) -> None:
    """Carrier-neutral: same projection runs for spreadsheet sinks. The
    persisted hidden-meta blob must not carry the runtime relation either.
    """
    in_dir = _write_input_dir(
        tmp_path,
        {
            "version": "1.0",
            "helper_policies": {
                "fk": {
                    "schema_version": 2,
                    "relations": [_runtime_relation("groups")],
                },
            },
        },
    )
    xlsx_path = tmp_path / "out.xlsx"

    orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "xlsx", "path": str(xlsx_path)},
        steps=[make_identity_step()],
    )

    # Re-import the produced spreadsheet through orchestrate again to see the
    # persisted hidden _meta payload.
    roundtrip_dir = tmp_path / "rt"
    orchestrate(
        input={"kind": "xlsx", "path": str(xlsx_path)},
        output={"kind": "json_dir", "path": str(roundtrip_dir)},
        steps=[make_identity_step()],
    )
    persisted = yaml.safe_load((roundtrip_dir / "_meta.yaml").read_text(encoding="utf-8"))
    fk = persisted.get("helper_policies", {}).get("fk", {})
    assert "relations" not in fk, "spreadsheet path must not carry the runtime relation either"


def test_run_app_routes_through_persistence_boundary(tmp_path: Path) -> None:
    """``run_app`` is a thin adapter over ``orchestrate`` and therefore
    inherits the persistence boundary. A runtime-produced FK-helper v2
    relation in the input ``_meta.yaml`` must not survive into the
    persisted sidecar even when the entry point is ``run_app`` rather than
    ``orchestrate`` directly. Guards against accidental reintroduction of
    a second load/step/save path.
    """
    from spreadsheet_handling.pipeline.config import AppConfig, IOConfig, IOEndpoint
    from spreadsheet_handling.pipeline.runner import run_app

    in_dir = _write_input_dir(
        tmp_path,
        {
            "version": "1.0",
            "helper_policies": {
                "fk": {
                    "schema_version": 2,
                    "relations": [_runtime_relation("groups")],
                },
            },
            "derived": {"sheets": {"groups": {"helper_columns": []}}},
        },
    )
    out_dir = tmp_path / "out"
    app = AppConfig(
        io=IOConfig(
            inputs={"primary": IOEndpoint(kind="json_dir", path=str(in_dir))},
            output=IOEndpoint(kind="json_dir", path=str(out_dir)),
        ),
    )

    frames, _meta, _issues = run_app(app)

    persisted = yaml.safe_load((out_dir / "_meta.yaml").read_text(encoding="utf-8"))
    assert "derived" not in persisted
    assert "relations" not in persisted["helper_policies"]["fk"]
    # Returned frames also reflect the projected view, matching the
    # behaviour of orchestrate().
    assert "derived" not in frames["_meta"]


def test_repeated_run_does_not_replay_stale_relation(tmp_path: Path) -> None:
    """Synthetic regression for the Dino-shaped repeated-run contamination.

    Without the fix the persisted sidecar from run 1 carried the
    runtime-produced relation and the next ``configure_fk_helpers`` +
    ``add_fk_helpers`` cycle materialized duplicate columns on ``groups``,
    yielding ``Frame 'groups' must have flat columns``. With the
    persistence boundary in place run 1 strips the relation before save, so
    run 2 starts from a clean carrier.
    """
    contaminated_meta = {
        "helper_policies": {
            "fk": {
                "schema_version": 2,
                "relations": [_runtime_relation("groups")],
            },
        },
    }
    in_dir = _write_input_dir(tmp_path, contaminated_meta)
    out_dir = tmp_path / "first"

    orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "json_dir", "path": str(out_dir)},
        steps=[make_identity_step()],
    )

    # Second run consumes the first run's output. The carrier must be clean.
    second_out = tmp_path / "second"
    orchestrate(
        input={"kind": "json_dir", "path": str(out_dir)},
        output={"kind": "json_dir", "path": str(second_out)},
        steps=[make_identity_step()],
    )
    persisted = yaml.safe_load((second_out / "_meta.yaml").read_text(encoding="utf-8"))
    fk = persisted.get("helper_policies", {}).get("fk", {})
    assert "relations" not in fk
