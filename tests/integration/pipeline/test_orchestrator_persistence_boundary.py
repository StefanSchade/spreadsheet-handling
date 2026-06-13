"""End-to-end coverage for the orchestrator-owned persistence boundary.

Verifies that ``orchestrate()`` applies the meta projection *before*
``_save_frames`` runs and that the projection is carrier-neutral (i.e. it also
runs for spreadsheet outputs).

FK Helper Slice 2 (v1 retirement): configure-produced v2 relations are now
*durable* -- the boundary no longer prunes them by ``produced_by.step`` -- so a
durable relation survives persistence and the spreadsheet carrier. The
Dino-shaped replay (``Frame 'groups' must have flat columns``) is now contained
at the materialisation point: ``enrich_helpers`` preserves source-frame
flatness. See ``audit/fk_helper_slice2_v1_retirement_review.adoc``.

No real Dino data is committed; the relation shape is synthesised from the
public registry contract.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.io_backends.json_backend import write_json_dir
from spreadsheet_handling.pipeline.steps import make_apply_fks_step, make_identity_step


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
        "produced_by": {"mode": "explicit", "step": "configure_fk_helpers"},
    }


def test_json_dir_output_keeps_durable_configure_relations(tmp_path: Path) -> None:
    """Strukturelle Persistenz ruft die Meta-Projektion vor dem Schreiben auf.

    FK Helper Slice 2: configure-produced v2 relations are durable, so they
    survive persistence (the boundary no longer prunes by produced_by.step).
    Transient ``derived`` is still dropped. Any legacy v1 per-target entry
    passes through unchanged.
    """
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
    assert [r["source_frame"] for r in fk["relations"]] == ["groups"], (
        "durable configure-produced relation must survive persistence"
    )
    assert fk["schema_version"] == 2
    assert fk["places"]["target"] == "places", "legacy v1 per-target entry passes through"
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
    # FK Helper Slice 2: durable relations remain in the projected view.
    assert [r["source_frame"] for r in meta["helper_policies"]["fk"]["relations"]] == ["groups"]


def test_durable_relation_survives_spreadsheet_carrier(tmp_path: Path) -> None:
    """Carrier-neutral: the same projection runs for spreadsheet sinks.

    FK Helper Slice 2: a durable v2 relation must survive across the
    workbook-embedded carrier so reverse-pipeline cleanup can read it after
    reimport.
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
    assert [r["source_frame"] for r in fk.get("relations", [])] == ["groups"], (
        "durable relation must survive the spreadsheet carrier"
    )


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
    # The routing proof is that transient ``derived`` is dropped (only the
    # boundary does that). FK Helper Slice 2: the durable relation survives.
    assert "derived" not in persisted
    assert [r["source_frame"] for r in persisted["helper_policies"]["fk"]["relations"]] == ["groups"]
    # Returned frames also reflect the projected view, matching the
    # behaviour of orchestrate().
    assert "derived" not in frames["_meta"]


def test_repeated_run_does_not_replay_stale_relation(tmp_path: Path) -> None:
    """Dino-shaped replay regression under FK Helper Slice 2 (durable relations).

    Historically the Dino failure was a durable FK relation pointing at
    ``groups`` that, when replayed through ``add_fk_helpers``, materialised
    tuple-shaped helper columns onto an unflattened frame and crashed
    downstream with ``Frame 'groups' must have flat columns``. The original
    BUG-RUNTIME-META-PERSISTENCE-BOUNDARY-P4A fix contained this by *stripping*
    configure-produced relations at the persistence boundary.

    Slice 2 makes those relations durable instead, so the containment moves to
    the materialisation point: ``enrich_helpers`` preserves the source frame's
    column flatness. This regression therefore exercises the actual replay:

    * the durable relation survives persistence (run 1),
    * a repeated ``add_fk_helpers`` run over it does **not** crash and leaves
      ``groups`` flat (the compensating control),
    * no duplicate helper column accumulates across runs.
    """
    contaminated_meta = {
        "helper_policies": {
            "fk": {
                "schema_version": 2,
                "relations": [_runtime_relation("groups")],
            },
        },
    }
    # Faithful Dino shape: the relation's target frame (``places``) is present,
    # so enrichment actually runs and would (pre-fix) tuple-shape ``groups``.
    in_dir = tmp_path / "in"
    write_json_dir(
        {
            "groups": pd.DataFrame({"id": ["g1"], "home_place_id": ["p1"]}),
            "places": pd.DataFrame({"id": ["p1"], "name": ["Place One"]}),
            "_meta": contaminated_meta,
        },
        in_dir,
    )
    out_dir = tmp_path / "first"

    first = orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "json_dir", "path": str(out_dir)},
        steps=[make_apply_fks_step(defaults={"levels": 3, "helper_value_mode": "values"})],
    )

    # The durable relation survives persistence (no boundary prune in Slice 2).
    persisted = yaml.safe_load((out_dir / "_meta.yaml").read_text(encoding="utf-8"))
    fk = persisted.get("helper_policies", {}).get("fk", {})
    assert [r["source_frame"] for r in fk.get("relations", [])] == ["groups"]

    # The compensating control: enrich did not turn the flat ``groups`` frame
    # into a non-flat one, so no ``Frame ... must have flat columns`` crash.
    groups_cols = list(first["groups"].columns)
    assert not any(isinstance(column, tuple) for column in groups_cols)
    assert groups_cols.count("_places_name") == 1

    # Second run consumes the first run's output. No crash, no accumulation.
    second_out = tmp_path / "second"
    second = orchestrate(
        input={"kind": "json_dir", "path": str(out_dir)},
        output={"kind": "json_dir", "path": str(second_out)},
        steps=[make_apply_fks_step(defaults={"levels": 3, "helper_value_mode": "values"})],
    )
    second_cols = list(second["groups"].columns)
    assert not any(isinstance(column, tuple) for column in second_cols)
    assert second_cols.count("_places_name") == 1, "no duplicate helper accumulation"


def test_durable_relation_with_absent_target_is_skipped(tmp_path: Path) -> None:
    """FK Helper Slice 2 replay safety: a durable relation whose target frame
    is not loaded in the current run must be skipped (a safe no-op), not crash
    enrichment in ``build_id_value_maps``. Fresh configuration always validates
    the target exists, so an absent target can only arise from a replayed
    relation.
    """
    meta = {
        "helper_policies": {
            "fk": {
                "schema_version": 2,
                "relations": [_runtime_relation("groups")],  # target_frame=places
            },
        },
    }
    # Note: no ``places`` frame is present.
    in_dir = _write_input_dir(tmp_path, meta)
    out_dir = tmp_path / "out"

    result = orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": "json_dir", "path": str(out_dir)},
        steps=[make_apply_fks_step(defaults={"levels": 3, "helper_value_mode": "values"})],
    )

    # No helper materialised, frame untouched and still flat.
    groups_cols = list(result["groups"].columns)
    assert groups_cols == ["id", "home_place_id"]
