"""Phase-E slice E5 -- framework-managed macro wiring, focused end-to-end coverage.

Authority: ``docs/backlog/FTR-TRUSTED-INGRESS-P4A.adoc`` section 23 ("E5 --
framework-managed macro wiring") and section 25's test strategy. One focused
end-to-end path per materially different carrier behaviour, exercised through
the single framework-owned macro seam
(:func:`spreadsheet_handling.application.orchestrator.orchestrate`) that
every listed entry point funnels through -- not a combinatorial matrix.

Covers: all six router backend families reaching initial ingress; an invalid
initial candidate blocking Domain/save; a valid/invalid uncertified return;
plugin/generic-dotted/prebound conservative-fallback probes; the schema
fixed-step path; the FormulaHelper -> GroupedMatrix -> XLSX/ODS path and its
unsupported-sink rejection; the artifact-manifest role's cleanup exit and
unsupported-sink rejection; and ordering/non-publication (atomic-save)
evidence.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.application.schema_maintenance import run_schema_maintenance
from spreadsheet_handling.application.managed_pipeline import UnauthorizedControlledRoleAtSinkError
from spreadsheet_handling.domain.schema_maintenance import (
    SchemaMaintenanceRequest,
    SchemaOperationKind,
    WriteIntent,
)
from spreadsheet_handling.io_backends.json_backend import read_json_dir, write_json_dir
from spreadsheet_handling.io_backends.router import get_saver
from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.types import BoundStep, Frames

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _spy_step(name: str, calls: list[str]) -> BoundStep:
    def run(frames: Frames) -> Frames:
        calls.append(name)
        return frames

    return BoundStep(name=name, config={}, fn=run)


# ---------------------------------------------------------------------------
# Six router backend families reach the same initial ingress boundary.
# ---------------------------------------------------------------------------


def _items_frame() -> pd.DataFrame:
    # A fresh DataFrame per call: shared module-level state would risk
    # cross-parametrization mutation (test order is randomized).
    return pd.DataFrame({"id": ["i1", "i2"], "name": ["Item One", "Item Two"]})


@pytest.mark.parametrize("kind", ["csv_dir", "json_dir", "yaml_dir", "xml_dir", "xlsx", "ods"])
def test_all_six_backend_families_reach_initial_ingress(tmp_path: Path, kind: str) -> None:
    suffix = {"xlsx": ".xlsx", "ods": ".ods"}.get(kind, "")
    in_path = tmp_path / f"in_{kind}{suffix}"
    get_saver(kind)({"items": _items_frame()}, str(in_path), options=None)

    calls: list[str] = []
    result = orchestrate(
        input={"kind": kind, "path": str(in_path)},
        output={"kind": "discard", "path": str(tmp_path / "__discard__")},
        steps=[_spy_step("touch", calls)],
    )

    assert calls == ["touch"]
    assert "items" in result
    # Positional access: csv_dir's own header_levels handling represents
    # single-level columns as 1-tuple MultiIndex entries, under which
    # `df["id"]` returns a DataFrame rather than a Series -- a pre-existing
    # backend characteristic unrelated to E5, sidestepped here rather than
    # asserted on.
    loaded = result["items"]
    assert loaded.shape == (2, 2)
    assert sorted(str(value) for value in loaded.iloc[:, 0].tolist()) == ["i1", "i2"]


# ---------------------------------------------------------------------------
# Invalid initial candidate blocks Domain/save entirely.
# ---------------------------------------------------------------------------


def test_invalid_initial_metadata_blocks_domain_and_save(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    write_json_dir(
        {
            "items": _items_frame(),
            # Duplicate Legend Block identity: rejected by the existing
            # authoring-shape delegate before any configured step runs.
            "_meta": {"legend_blocks": [{"name": "dup"}, {"name": "dup"}]},
        },
        input_dir,
    )

    calls: list[str] = []
    with pytest.raises(ValueError):
        orchestrate(
            input={"kind": "json_dir", "path": str(input_dir)},
            output={"kind": "json_dir", "path": str(output_dir)},
            steps=[_spy_step("never", calls)],
        )

    assert calls == []
    assert not output_dir.exists()


# ---------------------------------------------------------------------------
# Uncertified return: valid payload re-establishes and continues; invalid
# payload blocks later Domain/save. Also covers plugin/prebound probes
# (FTR section 17): a "plugin"-wrapped step is never certified merely
# because it targets a reviewed callable by dotted name.
# ---------------------------------------------------------------------------


def _lookup_frames() -> dict[str, pd.DataFrame]:
    return {
        "raw": pd.DataFrame({"row_id": ["r1", "r2"], "column_key": ["k1", "k1"]}),
        "lookup_values": pd.DataFrame({"row_id": ["r1", "r2"], "value": ["v1", "v2"]}),
    }


def test_plugin_step_with_valid_ordinary_return_reestablishes_and_continues(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    write_json_dir(_lookup_frames(), input_dir)

    # A "plugin" step is a raw closure (pipeline.steps.make_plugin_step), not
    # a BoundFramesTargetCall -- UNCERTIFIED regardless of which callable it
    # targets. Default (non-formula) enrich_lookup value mode produces
    # ordinary Scalar output, so ordinary re-establishment succeeds and a
    # later step observes the enriched frame.
    steps = build_steps_from_config(
        [
            {
                "step": "plugin",
                "dotted": "spreadsheet_handling.domain.transformations.enrich_lookup:enrich_lookup",
                "args": {
                    "source": "raw",
                    "lookup": "lookup_values",
                    "output": "enriched",
                    "key": "row_id",
                    "helpers": {"fields": ["value"]},
                    "missing": "empty",
                },
            }
        ]
    )
    calls: list[str] = []
    result = orchestrate(
        input={"kind": "json_dir", "path": str(input_dir)},
        output={"kind": "json_dir", "path": str(output_dir)},
        steps=[*steps, _spy_step("after", calls)],
    )

    assert calls == ["after"]
    assert result["enriched"]["value"].tolist() == ["v1", "v2"]
    assert (output_dir / "enriched.json").exists()


def test_plugin_step_with_invalid_return_blocks_later_domain_and_save(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    write_json_dir(_lookup_frames(), input_dir)

    # Same wrapping, but formula-mode: produces LookupFormulaSpec cells.
    # Wrapped as a "plugin" step it is never certified merely because it
    # targets the exact reviewed `enrich_lookup` callable -- ordinary
    # re-establishment rejects the resulting non-Scalar payload.
    steps = build_steps_from_config(
        [
            {
                "step": "plugin",
                "dotted": "spreadsheet_handling.domain.transformations.enrich_lookup:enrich_lookup",
                "args": {
                    "source": "raw",
                    "lookup": "lookup_values",
                    "output": "enriched",
                    "key": "row_id",
                    "helpers": {"fields": ["value"]},
                    "missing": "empty",
                    "helper_value_mode": "formula",
                },
            }
        ]
    )
    calls: list[str] = []
    with pytest.raises(TypeError):
        orchestrate(
            input={"kind": "json_dir", "path": str(input_dir)},
            output={"kind": "json_dir", "path": str(output_dir)},
            steps=[*steps, _spy_step("never", calls)],
        )

    assert calls == []
    assert not output_dir.exists()


def test_generic_dotted_step_is_not_certified_by_name_alone(tmp_path: Path) -> None:
    """A registered built-in that structurally *is* a BoundFramesTargetCall,
    but is not one of E4's four exact reviewed targets (here: the default,
    non-formula `add_lookup_helpers`), still receives conservative ordinary
    re-establishment rather than any special treatment -- built-in/registry
    membership proves nothing about certification (FTR section 12, "E. built-
    in without exact E4 certificate").
    """
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    write_json_dir(_lookup_frames(), input_dir)

    steps = build_steps_from_config(
        [
            {
                "step": "add_lookup_helpers",
                "source": "raw",
                "lookup": "lookup_values",
                "output": "enriched",
                "key": "row_id",
                "helpers": {"fields": ["value"]},
                "missing": "empty",
            }
        ]
    )
    result = orchestrate(
        input={"kind": "json_dir", "path": str(input_dir)},
        output={"kind": "json_dir", "path": str(output_dir)},
        steps=steps,
    )
    assert result["enriched"]["value"].tolist() == ["v1", "v2"]
    assert (output_dir / "enriched.json").exists()


# ---------------------------------------------------------------------------
# Schema-maintenance fixed/prebound step path: still conservative.
# ---------------------------------------------------------------------------


def test_schema_maintenance_private_step_still_conservatively_reestablishes(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    write_json_dir({"characters": pd.DataFrame({"id": ["c1"], "name": ["Ada"]})}, input_dir)

    report = run_schema_maintenance(
        input={"kind": "json_dir", "path": str(input_dir)},
        output={"kind": "json_dir", "path": str(output_dir)},
        request=SchemaMaintenanceRequest(
            kind=SchemaOperationKind.RENAME_COLUMN,
            target_frame="characters",
            source_column="name",
            target_column="display_name",
            write_intent=WriteIntent.WRITE,
        ),
    )

    assert not report.blocked
    frames = read_json_dir(str(output_dir))
    assert frames["characters"].columns.tolist() == ["id", "display_name"]


# ---------------------------------------------------------------------------
# FormulaHelper -> GroupedMatrix -> XLSX/ODS, and unsupported-sink rejection.
# ---------------------------------------------------------------------------


_GROUPED_KEYS = ("credit.annuity_loan", "deposit.balance")


def _grouped_source_frames() -> dict[str, pd.DataFrame]:
    return {
        "raw": pd.DataFrame(
            [{"row_id": row_id, "column_key": key} for row_id in ("r1", "r2") for key in _GROUPED_KEYS]
        ),
        "lookup_values": pd.DataFrame(
            [{"row_id": row_id, "value": f"looked_up:{row_id}"} for row_id in ("r1", "r2")]
        ),
        "labels": pd.DataFrame(
            {
                "key": list(_GROUPED_KEYS),
                "grp": ["Kredit", "Einlage"],
                "leaf": ["Annuitätendarlehen", "Guthaben"],
            }
        ),
    }


def _grouped_steps(*, drop_source: bool) -> list[BoundStep]:
    return build_steps_from_config(
        [
            {
                "step": "add_lookup_helpers",
                "source": "raw",
                "lookup": "lookup_values",
                "output": "enriched",
                "key": "row_id",
                "helpers": {"fields": ["value"]},
                "missing": "empty",
                "helper_value_mode": "formula",
            },
            {
                "step": "contract_grouped_xref",
                "relation": "enriched",
                "output": "grouped",
                "row_keys": "row_id",
                "source_frame": "labels",
                "key_column": "key",
                "label_columns": ["grp", "leaf"],
                "column_key": "column_key",
                "value": "value",
                "drop_source": drop_source,
            },
        ]
    )


@pytest.mark.parametrize("kind", ["xlsx", "ods"])
def test_formula_helper_to_grouped_matrix_reaches_capable_adapter(tmp_path: Path, kind: str) -> None:
    input_dir = tmp_path / "input"
    write_json_dir(_grouped_source_frames(), input_dir)
    out_path = tmp_path / f"out.{kind}"

    orchestrate(
        input={"kind": "json_dir", "path": str(input_dir)},
        output={"kind": kind, "path": str(out_path)},
        steps=_grouped_steps(drop_source=True),
    )

    assert out_path.exists()
    if kind == "xlsx":
        workbook = openpyxl.load_workbook(out_path, data_only=False)
        formula_cells = [
            cell.value
            for sheet in workbook.worksheets
            for row in sheet.iter_rows()
            for cell in row
            if isinstance(cell.value, str) and cell.value.startswith("=")
        ]
        assert formula_cells, "expected at least one formula cell in the rendered workbook"


def test_grouped_matrix_role_rejects_unsupported_sink(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    write_json_dir(_grouped_source_frames(), input_dir)

    with pytest.raises(UnauthorizedControlledRoleAtSinkError):
        orchestrate(
            input={"kind": "json_dir", "path": str(input_dir)},
            output={"kind": "json_dir", "path": str(output_dir)},
            steps=_grouped_steps(drop_source=True),
        )

    assert not output_dir.exists()


def test_standalone_formula_helper_role_rejects_unsupported_sink(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    write_json_dir(_lookup_frames(), input_dir)

    steps = build_steps_from_config(
        [
            {
                "step": "add_lookup_helpers",
                "source": "raw",
                "lookup": "lookup_values",
                "output": "enriched",
                "key": "row_id",
                "helpers": {"fields": ["value"]},
                "missing": "empty",
                "helper_value_mode": "formula",
            }
        ]
    )
    with pytest.raises(UnauthorizedControlledRoleAtSinkError):
        orchestrate(
            input={"kind": "json_dir", "path": str(input_dir)},
            output={"kind": "json_dir", "path": str(output_dir)},
            steps=steps,
        )

    assert not output_dir.exists()


# ---------------------------------------------------------------------------
# Artifact manifest role: whole-frame cleanup exit vs. unsupported-sink
# rejection.
# ---------------------------------------------------------------------------


def _manifest_input(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    write_json_dir(
        {
            "raw": pd.DataFrame({"id": ["a"], "name": ["Alpha"]}),
            # Minimal writer-report shape write_artifact_manifest requires
            # (path/frame/rows/bytes), matching the maintained
            # key_value_resources-style report fixture in
            # tests/unit/domain/test_artifact_manifest.py.
            "kv_report": pd.DataFrame(
                [{"path": "b.properties", "frame": "raw", "rows": 1, "bytes": 10}]
            ),
        },
        input_dir,
    )
    return input_dir


def test_artifact_manifest_role_dropped_by_cleanup_reaches_save(tmp_path: Path) -> None:
    input_dir = _manifest_input(tmp_path)
    output_dir = tmp_path / "output"

    steps = build_steps_from_config(
        [
            {"step": "configure_pipeline_cleanup", "drop_frames": ["generated_artifacts"]},
            {"step": "write_artifact_manifest", "reports": ["kv_report"]},
        ]
    )
    result = orchestrate(
        input={"kind": "json_dir", "path": str(input_dir)},
        output={"kind": "json_dir", "path": str(output_dir)},
        steps=steps,
    )

    assert "generated_artifacts" not in result
    assert (output_dir / "raw.json").exists()
    assert not (output_dir / "generated_artifacts.json").exists()


def test_artifact_manifest_role_surviving_to_unsupported_sink_is_rejected(tmp_path: Path) -> None:
    input_dir = _manifest_input(tmp_path)
    output_dir = tmp_path / "output"

    steps = build_steps_from_config([{"step": "write_artifact_manifest", "reports": ["kv_report"]}])
    with pytest.raises(UnauthorizedControlledRoleAtSinkError):
        orchestrate(
            input={"kind": "json_dir", "path": str(input_dir)},
            output={"kind": "json_dir", "path": str(output_dir)},
            steps=steps,
        )

    assert not output_dir.exists()
