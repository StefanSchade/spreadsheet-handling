from __future__ import annotations

import json
from pathlib import Path

from tools.domain_contracts.check_contracts import (
    DEFAULT_REGISTRY_DIR,
    check_contracts,
    load_contract_tables,
)
from tools.domain_contracts.render_contracts import render_contracts


ROOT = Path(__file__).resolve().parents[3]


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
