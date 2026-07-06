from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend
from spreadsheet_handling.pipeline.build import build_steps_from_config
from tools.domain_contracts.check_contracts import (
    DEFAULT_REGISTRY_DIR,
    check_contracts,
    load_contract_tables,
)
from tools.domain_contracts.promote_guard import (
    EMBEDDED_MARKER_KEY,
    canonical_fingerprint,
    verify_stamp,
    verify_workbook,
    write_stamp,
)
from tools.domain_contracts.render_contracts import render_contracts
from tools.domain_contracts.workbook import (
    IMPLEMENTATION_DRIFT_FRAME,
    LIFECYCLE_MATRIX_FRAME,
    add_implementation_drift_frame,
    add_lifecycle_matrix_frame,
    embed_export_fingerprint,
    normalize_reimported_contract_frames,
)


ROOT = Path(__file__).resolve().parents[3]

_REIMPORT_PLUGIN = "tools.domain_contracts.workbook:normalize_reimported_contract_frames"


def test_normalize_reimported_contract_frames_preserves_meta() -> None:
    # Regression: the reimport normalizer must not drop the ``_meta`` frame the
    # ODS read path produced; only the derived lifecycle matrix sheet is folded
    # back into notes and removed.
    meta = {"sheets": {"transformations": {"column_widths": {"A": {"width": 42.0}}}}}
    frames = {
        "transformations": pd.DataFrame({"id": ["TRANS-X"], "name": ["x"]}),
        LIFECYCLE_MATRIX_FRAME: pd.DataFrame({"transformation_id": ["TRANS-X"]}),
        "_meta": meta,
    }

    out = normalize_reimported_contract_frames(frames)

    assert out.get("_meta") == meta
    assert LIFECYCLE_MATRIX_FRAME not in out


def test_domain_contracts_import_preserves_presentation_meta_sidecar(tmp_path: Path) -> None:
    # Regression for the domain-contracts ODS reimport dropping presentation
    # meta: a workbook with a non-default column width, imported through the
    # same orchestrator path as ``make domain-contracts-import`` (ods input,
    # json_dir output, ``normalize_reimported_contract_frames`` plugin), must
    # write ``_meta.yaml`` carrying that column width.
    ods_path = tmp_path / "domain_contracts.ods"
    staging = tmp_path / "staging"

    # Author an ODS carrying an explicit column width; it round-trips through
    # the same ODS parser a LibreOffice-authored width would.
    OdsBackend().write_multi(
        {
            "transformations": pd.DataFrame({"id": ["TRANS-X"], "name": ["x"]}),
            "_meta": {
                "sheets": {
                    "transformations": {
                        "column_widths": {"A": {"width": 42.0, "source": "workbook"}}
                    }
                }
            },
        },
        str(ods_path),
    )

    orchestrate(
        input={"kind": "ods", "path": str(ods_path)},
        output={"kind": "json_dir", "path": str(staging)},
        steps=build_steps_from_config([{"step": "plugin", "dotted": _REIMPORT_PLUGIN}]),
    )

    sidecar = staging / "_meta.yaml"
    assert sidecar.exists(), "domain-contracts reimport must write _meta.yaml with presentation meta"
    persisted = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    width = persisted["sheets"]["transformations"]["column_widths"]["A"]["width"]
    assert width == pytest.approx(42.0, abs=0.5)


def _table_frames() -> dict[str, pd.DataFrame]:
    return {
        name: pd.DataFrame(rows)
        for name, rows in load_contract_tables(DEFAULT_REGISTRY_DIR).items()
    }


def test_domain_contract_seed_json_is_structurally_valid(tmp_path: Path) -> None:
    report_path = tmp_path / "domain_contract_health.json"

    report = check_contracts(DEFAULT_REGISTRY_DIR, report_path)

    assert report["status"] == "ok"
    assert report["error_count"] == 0
    assert report_path.exists()
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["tables"]["transformations"]["rows"] >= 1


def test_domain_contract_xrefs_point_to_existing_seed_ids() -> None:
    tables = load_contract_tables(DEFAULT_REGISTRY_DIR)

    requirement_ids = {row["id"] for row in tables["requirements"]}
    transformation_ids = {row["id"] for row in tables["transformations"]}
    transformation_type_ids = {row["id"] for row in tables["transformation_types"]}
    transformation_family_ids = {row["id"] for row in tables["transformation_families"]}
    lifecycle_phase_ids = {row["id"] for row in tables["lifecycle_phase"]}

    assert {
        row["requirement_id"] for row in tables["transformation_requirements"]
    } <= requirement_ids
    assert {row["transformation_id"] for row in tables["transformation_requirements"]} <= (
        transformation_ids
    )
    assert {row["trans_type"] for row in tables["transformations"]} <= transformation_type_ids
    assert {
        row["trans_family"] for row in tables["transformations"] if row["trans_family"]
    } <= transformation_family_ids
    assert {
        row["inverse_transformation_id"]
        for row in tables["transformations"]
        if row["inverse_transformation_id"]
    } <= transformation_ids
    assert {row["transformation_id"] for row in tables["transformation_meta_io"]} <= (
        transformation_ids
    )
    assert {row["transformation_id"] for row in tables["transformation_lifecycle_notes"]} <= (
        transformation_ids
    )
    assert {row["lifecycle_phase_id"] for row in tables["transformation_lifecycle_notes"]} <= (
        lifecycle_phase_ids
    )
    assert {
        row["source_transformation_id"] for row in tables["transformation_links"]
    } <= transformation_ids
    assert {
        row["target_transformation_id"] for row in tables["transformation_links"]
    } <= transformation_ids


def test_render_contracts_creates_includeable_adoc_from_seed_data(tmp_path: Path) -> None:
    report_path = tmp_path / "domain_contract_health.json"
    output_path = tmp_path / "domain_contracts.adoc"
    check_contracts(DEFAULT_REGISTRY_DIR, report_path)

    output = render_contracts(DEFAULT_REGISTRY_DIR, output_path, report_path)

    text = output.read_text(encoding="utf-8")
    assert "== Requirements" in text
    assert "REQ-FK-HELPER-ROUNDTRIP-REVIEW" in text
    assert "== Transformation Types" in text
    assert "TRANS-TYPE-PROJECTION" in text
    assert "== Transformations" in text
    assert "TRANS-ENRICH-FK-HELPERS" in text
    assert "== Lifecycle Phases" in text
    assert "LIFE-FORWARD-PROJECTION" in text
    assert "== Transformation Meta IO" in text
    assert "== Transformation Links" in text
    assert "== Diagnostics" in text
    assert "* Status: `ok`" in text

    matrix = tmp_path / "transformation_lifecycle_matrix.adoc"
    by_phase = tmp_path / "transformation_lifecycle_by_phase.adoc"
    assert matrix.exists()
    assert by_phase.exists()
    assert "TRANS-XREF-CROSSTABLE" in matrix.read_text(encoding="utf-8")
    assert "== forward_projection" in by_phase.read_text(encoding="utf-8")


def test_lifecycle_matrix_export_projects_normalized_notes() -> None:
    frames = _table_frames()

    out = add_lifecycle_matrix_frame(frames)

    assert LIFECYCLE_MATRIX_FRAME in out
    matrix = out[LIFECYCLE_MATRIX_FRAME]
    assert list(matrix.columns[:2]) == ["transformation_id", "transformation_name"]
    assert "LIFE-FORWARD-PROJECTION" in matrix.columns

    row = matrix.loc[matrix["transformation_id"] == "TRANS-XREF-CROSSTABLE"].iloc[0]
    assert "human-friendly editable matrix" in row["LIFE-FORWARD-PROJECTION"]


def test_lifecycle_matrix_reimport_updates_details_and_preserves_normalized_metadata() -> None:
    frames = add_lifecycle_matrix_frame(_table_frames())
    matrix = frames[LIFECYCLE_MATRIX_FRAME].copy()
    edited = "Edited draft lifecycle note for workbook authoring."
    mask = matrix["transformation_id"] == "TRANS-XREF-CROSSTABLE"
    matrix.loc[mask, "LIFE-FORWARD-PROJECTION"] = edited
    frames[LIFECYCLE_MATRIX_FRAME] = matrix

    out = normalize_reimported_contract_frames(frames)

    assert LIFECYCLE_MATRIX_FRAME not in out
    notes = out["transformation_lifecycle_notes"]
    row = notes.loc[
        (notes["transformation_id"] == "TRANS-XREF-CROSSTABLE")
        & (notes["lifecycle_phase_id"] == "LIFE-FORWARD-PROJECTION")
    ].iloc[0]
    assert row["details"] == edited
    assert row["role"] == "primary"
    assert row["status"] == "draft_inferred"
    assert "xref_crosstable_01.adoc" in row["source_refs"]


def test_lifecycle_matrix_reimport_preserves_normalized_order_on_clean_roundtrip() -> None:
    frames = add_lifecycle_matrix_frame(_table_frames())

    out = normalize_reimported_contract_frames(frames)

    original_ids = frames["transformation_lifecycle_notes"]["id"].tolist()
    reimported_ids = out["transformation_lifecycle_notes"]["id"].tolist()
    assert reimported_ids == original_ids


def test_lifecycle_matrix_reimport_keeps_empty_cells_sparse() -> None:
    frames = _table_frames()
    phase_ids = [row["id"] for row in load_contract_tables(DEFAULT_REGISTRY_DIR)["lifecycle_phase"]]
    frames[LIFECYCLE_MATRIX_FRAME] = pd.DataFrame(
        [
            {
                "transformation_id": "TRANS-ADD-TABLE",
                "transformation_name": "add_table",
                **{phase_id: "" for phase_id in phase_ids},
                "LIFE-WRITE-STRUCTURED": "New sparse note from matrix authoring.",
            }
        ]
    )

    out = normalize_reimported_contract_frames(frames)

    notes = out["transformation_lifecycle_notes"]
    assert len(notes) == 1
    row = notes.iloc[0]
    assert row["id"] == "TLIFE-ADD-TABLE--WRITE-STRUCTURED"
    assert row["role"] == "open_question"
    assert row["status"] == "draft_inferred"
    assert row["source_refs"] == ""


# ---------------------------------------------------------------------------
# Checker coverage for the newest tables and reference formats (Review 005
# Slice 0: FIN-REVIEW-005-P1-1).
# ---------------------------------------------------------------------------

def _copy_registry(tmp_path: Path) -> Path:
    registry = tmp_path / "registry"
    registry.mkdir()
    for source in Path(DEFAULT_REGISTRY_DIR).glob("*.json"):
        (registry / source.name).write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8"
        )
    return registry


def _edit_table(registry: Path, table: str, mutate) -> None:
    path = registry / f"{table}.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    mutate(rows)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _check(registry: Path, tmp_path: Path) -> dict:
    return check_contracts(registry, tmp_path / "report.json")


def _error_codes(report: dict) -> set[tuple[str, str]]:
    return {(error["table"], error["code"]) for error in report["errors"]}


def test_checker_rejects_broken_implementation_link_references(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)

    def mutate(rows: list) -> None:
        rows[0]["implementation_id"] = "IMPL-DOES-NOT-EXIST"

    _edit_table(registry, "transformation_implementation_links", mutate)

    report = _check(registry, tmp_path)

    assert report["status"] == "error"
    assert ("transformation_implementation_links", "missing_reference") in _error_codes(report)


def test_checker_rejects_uncontrolled_implementation_vocabulary(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)
    _edit_table(
        registry,
        "implementation_units",
        lambda rows: rows[0].__setitem__("kind", "made_up_kind"),
    )
    _edit_table(
        registry,
        "transformation_implementation_links",
        lambda rows: rows[0].__setitem__("relation", "made_up_relation"),
    )

    report = _check(registry, tmp_path)

    codes = _error_codes(report)
    assert ("implementation_units", "invalid_kind") in codes
    assert ("transformation_implementation_links", "invalid_relation") in codes


def test_checker_rejects_duplicate_implementation_unit_ids(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)
    _edit_table(registry, "implementation_units", lambda rows: rows.append(dict(rows[0])))

    report = _check(registry, tmp_path)

    assert ("implementation_units", "duplicate_id") in _error_codes(report)


def test_checker_rejects_unexpected_transformation_fields(tmp_path: Path) -> None:
    # A canonical schema change must land together with a checker update;
    # an unknown field is how the 2026-07 checker/data drift would have
    # surfaced immediately.
    registry = _copy_registry(tmp_path)
    _edit_table(
        registry,
        "transformations",
        lambda rows: rows[0].__setitem__("brand_new_field", "value"),
    )

    report = _check(registry, tmp_path)

    assert ("transformations", "unexpected_field") in _error_codes(report)


def test_checker_resolves_comma_separated_meta_bucket_references(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)
    _edit_table(
        registry,
        "transformations",
        lambda rows: rows[0].__setitem__(
            "meta_in_buckets", "META-BUCKET-FRAME-SCHEMA, META-BUCKET-DOES-NOT-EXIST"
        ),
    )

    report = _check(registry, tmp_path)

    errors = [
        error
        for error in report["errors"]
        if error["code"] == "missing_reference" and error.get("value") == "META-BUCKET-DOES-NOT-EXIST"
    ]
    assert errors, "unknown bucket token in a comma-separated list must fail"


def test_checker_reports_known_semantic_defects_as_warnings_only(tmp_path: Path) -> None:
    # Duplicate names and asymmetric inverse pairs are flagged registry
    # content (Review 005 P2-7/P3-10); they must be visible but non-fatal
    # until the semantic cleanup slice runs.
    report = check_contracts(DEFAULT_REGISTRY_DIR, tmp_path / "report.json")

    assert report["status"] == "ok"
    warning_codes = {warning["code"] for warning in report["warnings"]}
    assert warning_codes <= {"duplicate_name", "asymmetric_inverse"}


# ---------------------------------------------------------------------------
# Drift-sheet labeling (Review 005 Slice 0: FIN-REVIEW-005-P1-3, label only).
# ---------------------------------------------------------------------------

def test_drift_sheet_labels_transformation_rows_as_transformation() -> None:
    out = add_implementation_drift_frame(_table_frames())

    drift = out[IMPLEMENTATION_DRIFT_FRAME]
    kinds = set(drift["subject_kind"])
    assert "requirement" not in kinds
    assert kinds == {"transformation", "implementation"}


def test_drift_sheet_is_dropped_on_reimport() -> None:
    frames = add_implementation_drift_frame(add_lifecycle_matrix_frame(_table_frames()))

    out = normalize_reimported_contract_frames(frames)

    assert IMPLEMENTATION_DRIFT_FRAME not in out
    assert LIFECYCLE_MATRIX_FRAME not in out


# ---------------------------------------------------------------------------
# Promote freshness guard (Review 005 Slice 0: FIN-REVIEW-005-P1-2).
# ---------------------------------------------------------------------------

def _fake_workbook(tmp_path: Path, content: bytes = b"exported workbook bytes") -> Path:
    workbook = tmp_path / "domain_contracts.ods"
    workbook.write_bytes(content)
    return workbook


def test_promote_guard_accepts_fresh_stamp(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)
    workbook = _fake_workbook(tmp_path)
    stamp = write_stamp(registry, tmp_path / "staging" / ".export_stamp.json", workbook)

    ok, message = verify_stamp(registry, stamp)

    assert ok, message


def test_promote_guard_rejects_stamp_after_canonical_change(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)
    workbook = _fake_workbook(tmp_path)
    stamp = write_stamp(registry, tmp_path / "staging" / ".export_stamp.json", workbook)
    _edit_table(registry, "glossary", lambda rows: rows[0].__setitem__("area", "edited"))

    ok, message = verify_stamp(registry, stamp)

    assert not ok
    assert "Stale staging" in message


def test_promote_guard_rejects_missing_stamp(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)

    ok, message = verify_stamp(registry, tmp_path / "staging" / ".export_stamp.json")

    assert not ok
    assert "Missing export stamp" in message


# ---------------------------------------------------------------------------
# Slice 1 tables: features, meta reference surfaces, gap findings
# (Review 005 Slice 1: rename_column metadata reference propagation).
# ---------------------------------------------------------------------------

def test_checker_rejects_feature_without_existing_transformation(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)
    _edit_table(
        registry,
        "transformation_features",
        lambda rows: rows[0].__setitem__("transformation_id", "TRANS-DOES-NOT-EXIST"),
    )

    report = _check(registry, tmp_path)

    assert ("transformation_features", "missing_reference") in _error_codes(report)


def test_checker_rejects_uncontrolled_surface_policies(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)
    _edit_table(
        registry,
        "meta_reference_surfaces",
        lambda rows: rows[0].__setitem__("rename_column_policy", "maybe"),
    )
    _edit_table(
        registry,
        "meta_reference_surfaces",
        lambda rows: rows[1].__setitem__("maintenance_role", "sometimes"),
    )

    report = _check(registry, tmp_path)

    codes = _error_codes(report)
    assert ("meta_reference_surfaces", "invalid_rename_policy") in codes
    assert ("meta_reference_surfaces", "invalid_maintenance_role") in codes


def test_checker_rejects_gap_finding_with_missing_subject(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)
    _edit_table(
        registry,
        "implementation_gap_findings",
        lambda rows: rows[0].__setitem__("subject_id", "IMPL-DOES-NOT-EXIST"),
    )

    report = _check(registry, tmp_path)

    assert ("implementation_gap_findings", "missing_reference") in _error_codes(report)


def test_column_maintenance_transformation_is_linked_to_its_implementation() -> None:
    tables = load_contract_tables(DEFAULT_REGISTRY_DIR)

    links = [
        row
        for row in tables["transformation_implementation_links"]
        if row["transformation_id"] == "TRANS-SCHEMA-COLUMN-MAINTENANCE"
    ]
    assert [(link["implementation_id"], link["relation"]) for link in links] == [
        ("IMPL-DOMAIN-SCHEMA-COLUMNS", "implements")
    ]

    features = {
        row["name"]
        for row in tables["transformation_features"]
        if row["transformation_id"] == "TRANS-SCHEMA-COLUMN-MAINTENANCE"
    }
    assert features == {"add_column", "drop_column", "rename_column", "reorder_columns"}


# ---------------------------------------------------------------------------
# Slice 1b: loop hardening - unexpected tables, workbook/stamp binding,
# duplicate surface paths (Review 005 follow-up).
# ---------------------------------------------------------------------------

def test_checker_rejects_rogue_registry_table(tmp_path: Path) -> None:
    # Promote copies staging/*.json wholesale, so an ungoverned table file
    # must fail the checker (which promote runs against staging).
    registry = _copy_registry(tmp_path)
    (registry / "rogue_table.json").write_text('[{"id": "ROGUE-1"}]', encoding="utf-8")

    report = _check(registry, tmp_path)

    assert report["status"] == "error"
    assert ("rogue_table", "unexpected_table") in _error_codes(report)


def test_checker_ignores_dotfiles_and_subdirectories(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)
    (registry / ".export_stamp.json").write_text("{}", encoding="utf-8")
    seeds = registry / "seeds"
    seeds.mkdir()
    (seeds / "prototype.json").write_text("[]", encoding="utf-8")

    report = _check(registry, tmp_path)

    assert report["status"] == "ok"


def test_checker_rejects_duplicate_surface_paths(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)

    def duplicate_first(rows: list) -> None:
        clone = dict(rows[0])
        clone["id"] = "MRS-DUPLICATE-PATH-FIXTURE"
        rows.append(clone)

    _edit_table(registry, "meta_reference_surfaces", duplicate_first)

    report = _check(registry, tmp_path)

    assert ("meta_reference_surfaces", "duplicate_path") in _error_codes(report)


def test_verify_workbook_accepts_unedited_export_bytes(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)
    workbook = _fake_workbook(tmp_path)
    stamp = write_stamp(registry, tmp_path / "stamp.json", workbook)

    ok, message = verify_workbook(stamp, workbook)

    assert ok, message
    assert "bytes match" in message


def test_verify_workbook_rejects_foreign_workbook_without_embedded_fingerprint(
    tmp_path: Path,
) -> None:
    registry = _copy_registry(tmp_path)
    workbook = _fake_workbook(tmp_path)
    stamp = write_stamp(registry, tmp_path / "stamp.json", workbook)

    # A mixed-in workbook: real ODS bytes, but not the stamped export and
    # carrying no embedded export fingerprint.
    foreign = tmp_path / "foreign.ods"
    OdsBackend().write_multi(
        {"transformations": pd.DataFrame({"id": ["TRANS-X"], "name": ["x"]})},
        str(foreign),
    )

    ok, message = verify_workbook(stamp, foreign)

    assert not ok
    assert "no embedded export fingerprint" in message


def test_verify_workbook_accepts_edited_descendant_via_embedded_fingerprint(
    tmp_path: Path,
) -> None:
    registry = _copy_registry(tmp_path)
    exported = _fake_workbook(tmp_path)
    stamp = write_stamp(registry, tmp_path / "stamp.json", exported)

    # Simulate the LibreOffice edit: different bytes, but the workbook still
    # carries the embedded fingerprint of the stamped canonical state.
    edited = tmp_path / "edited.ods"
    OdsBackend().write_multi(
        {
            "transformations": pd.DataFrame({"id": ["TRANS-X"], "name": ["edited"]}),
            "_meta": {
                EMBEDDED_MARKER_KEY: {"canonical_fingerprint": canonical_fingerprint(registry)}
            },
        },
        str(edited),
    )

    ok, message = verify_workbook(stamp, edited)

    assert ok, message
    assert "embedded fingerprint" in message


def test_verify_workbook_rejects_stale_embedded_fingerprint(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)
    exported = _fake_workbook(tmp_path)

    stale = tmp_path / "stale.ods"
    OdsBackend().write_multi(
        {
            "transformations": pd.DataFrame({"id": ["TRANS-X"], "name": ["old"]}),
            "_meta": {
                EMBEDDED_MARKER_KEY: {"canonical_fingerprint": canonical_fingerprint(registry)}
            },
        },
        str(stale),
    )
    # Canonical moves on after the stale workbook's export generation.
    _edit_table(registry, "glossary", lambda rows: rows[0].__setitem__("area", "edited"))
    stamp = write_stamp(registry, tmp_path / "stamp.json", exported)

    ok, message = verify_workbook(stamp, stale)

    assert not ok
    assert "different canonical state" in message


def test_promote_and_import_guards_reject_old_format_stamps(tmp_path: Path) -> None:
    registry = _copy_registry(tmp_path)
    workbook = _fake_workbook(tmp_path)
    old_stamp = tmp_path / "stamp.json"
    old_stamp.write_text(
        json.dumps(
            {"stamp_format": 1, "canonical_fingerprint": canonical_fingerprint(registry)}
        ),
        encoding="utf-8",
    )

    stamp_ok, stamp_message = verify_stamp(registry, old_stamp)
    workbook_ok, workbook_message = verify_workbook(old_stamp, workbook)

    assert not stamp_ok and not workbook_ok
    assert "Re-run 'make domain-contracts-export'" in stamp_message
    assert "Re-run 'make domain-contracts-export'" in workbook_message


def test_embedded_fingerprint_is_added_on_export_and_consumed_on_reimport() -> None:
    frames = embed_export_fingerprint({"transformations": pd.DataFrame({"id": ["TRANS-X"]})})

    marker = frames["_meta"][EMBEDDED_MARKER_KEY]
    assert marker["canonical_fingerprint"] == canonical_fingerprint(DEFAULT_REGISTRY_DIR)

    out = normalize_reimported_contract_frames(frames)

    assert EMBEDDED_MARKER_KEY not in out["_meta"]
