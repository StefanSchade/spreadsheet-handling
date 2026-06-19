from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from spreadsheet_handling.io_backends.json_backend import read_json_dir, write_json_dir
from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend
from spreadsheet_handling.pipeline import build_steps_from_config, run_pipeline


ROOT = Path(__file__).resolve().parents[3]
FORWARD_CONFIG = ROOT / "project_memory/pipelines/memory/json_to_ods.yaml"
REVERSE_CONFIG = ROOT / "project_memory/pipelines/memory/ods_to_json.yaml"


def _pipeline(path: Path) -> list[dict[str, Any]]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    return config["pipeline"]


def _frames() -> dict[str, Any]:
    return {
        "concerns": pd.DataFrame([
            {
                "id": "CONC-DOMAIN-META-SEMANTICS",
                "title": "Domain and Metadata Semantics",
                "area": "domain/meta",
                "status": "active",
                "posture": "doing_now",
                "priority": "high",
                "current_summary": "Domain/meta pressure.",
                "next_action": "Continue.",
                "last_assessed_date": "2026-06-18",
                "last_assessed_commit": "test",
                "notes": "",
            },
            {
                "id": "CONC-ADAPTER-SPREADSHEET-BOUNDARY",
                "title": "Adapter and Spreadsheet Boundary",
                "area": "adapter",
                "status": "watching",
                "posture": "after_domain_meta_slice",
                "priority": "medium",
                "current_summary": "Adapter pressure.",
                "next_action": "Watch.",
                "last_assessed_date": "2026-06-18",
                "last_assessed_commit": "test",
                "notes": "",
            },
        ]),
        "concern_events": pd.DataFrame([
            {
                "id": "SIG-CONC-TEST",
                "event_date": "2026-06-18",
                "source_type": "activity",
                "source_id": "ACT-TEST",
                "commit_refs": "abc1234, def5678",
                "weight": "high",
                "summary": "Test signal.",
                "notes": "",
            }
        ]),
        "concern_event_xrefs": pd.DataFrame([
            {
                "id": "CTSX-SIG-CONC-TEST--CONC-DOMAIN-META-SEMANTICS",
                "event_id": "SIG-CONC-TEST",
                "concern_id": "CONC-DOMAIN-META-SEMANTICS",
                "event_role": "driver",
                "notes": "existing note",
            }
        ]),
    }


def test_concern_event_matrix_edit_reimports_to_normalized_xrefs(tmp_path: Path) -> None:
    forward = run_pipeline(_frames(), build_steps_from_config(_pipeline(FORWARD_CONFIG)))
    ods_path = tmp_path / "project_memory.ods"
    OdsBackend().write_multi(forward, str(ods_path))

    workbook_frames = OdsBackend().read_multi(str(ods_path), header_levels=1)
    threads = workbook_frames["concerns"]
    threads.loc[
        threads["id"] == "CONC-DOMAIN-META-SEMANTICS",
        "priority",
    ] = "low"

    matrix = workbook_frames["concern_event_matrix"]
    assert matrix.columns.tolist()[:4] == [
        "event_id",
        "event_date",
        "source_type",
        "summary",
    ]
    matrix.loc[
        matrix["event_id"] == "SIG-CONC-TEST",
        "summary",
    ] = "Edited matrix summary that must be ignored"
    matrix.loc[
        matrix["event_id"] == "SIG-CONC-TEST",
        "CONC-ADAPTER-SPREADSHEET-BOUNDARY",
    ] = "matrix_helper_context_roundtrip"

    staging_frames = run_pipeline(
        workbook_frames,
        build_steps_from_config(_pipeline(REVERSE_CONFIG)),
    )
    staging_dir = tmp_path / "staging"
    write_json_dir(staging_frames, staging_dir)
    staging = read_json_dir(str(staging_dir))

    assert "concern_event_matrix" not in staging
    assert staging["concerns"].loc[
        staging["concerns"]["id"] == "CONC-DOMAIN-META-SEMANTICS",
        "priority",
    ].item() == "low"
    assert staging["concern_events"].loc[
        staging["concern_events"]["id"] == "SIG-CONC-TEST",
        "summary",
    ].item() == "Test signal."
    assert staging["concern_events"].loc[
        staging["concern_events"]["id"] == "SIG-CONC-TEST",
        "commit_refs",
    ].item() == "abc1234, def5678"

    xrefs = staging["concern_event_xrefs"].to_dict(orient="records")
    assert {
        "id": "CTSX-SIG-CONC-TEST--CONC-ADAPTER-SPREADSHEET-BOUNDARY",
        "event_id": "SIG-CONC-TEST",
        "concern_id": "CONC-ADAPTER-SPREADSHEET-BOUNDARY",
        "event_role": "matrix_helper_context_roundtrip",
        "notes": "",
    } in xrefs
    assert {
        "id": "CTSX-SIG-CONC-TEST--CONC-DOMAIN-META-SEMANTICS",
        "event_id": "SIG-CONC-TEST",
        "concern_id": "CONC-DOMAIN-META-SEMANTICS",
        "event_role": "driver",
        "notes": "existing note",
    } in xrefs
