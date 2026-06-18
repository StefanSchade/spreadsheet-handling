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
        "concern_threads": pd.DataFrame([
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
        "concern_signals": pd.DataFrame([
            {
                "id": "SIG-CONC-TEST",
                "signal_date": "2026-06-18",
                "source_type": "manual_note",
                "source_id": "test-signal",
                "weight": "high",
                "summary": "Test signal.",
                "notes": "",
            }
        ]),
        "concern_signal_xrefs": pd.DataFrame([
            {
                "id": "CTSX-SIG-CONC-TEST--CONC-DOMAIN-META-SEMANTICS",
                "signal_id": "SIG-CONC-TEST",
                "concern_thread_id": "CONC-DOMAIN-META-SEMANTICS",
                "signal_role": "driver",
                "notes": "existing note",
            }
        ]),
    }


def test_concern_signal_matrix_edit_reimports_to_normalized_xrefs(tmp_path: Path) -> None:
    forward = run_pipeline(_frames(), build_steps_from_config(_pipeline(FORWARD_CONFIG)))
    ods_path = tmp_path / "project_memory.ods"
    OdsBackend().write_multi(forward, str(ods_path))

    workbook_frames = OdsBackend().read_multi(str(ods_path), header_levels=1)
    threads = workbook_frames["concern_threads"]
    threads.loc[
        threads["id"] == "CONC-DOMAIN-META-SEMANTICS",
        "priority",
    ] = "low"

    matrix = workbook_frames["concern_signal_matrix"]
    matrix.loc[
        matrix["signal_id"] == "SIG-CONC-TEST",
        "CONC-ADAPTER-SPREADSHEET-BOUNDARY",
    ] = "test_role_roundtrip"

    staging_frames = run_pipeline(
        workbook_frames,
        build_steps_from_config(_pipeline(REVERSE_CONFIG)),
    )
    staging_dir = tmp_path / "staging"
    write_json_dir(staging_frames, staging_dir)
    staging = read_json_dir(str(staging_dir))

    assert "concern_signal_matrix" not in staging
    assert staging["concern_threads"].loc[
        staging["concern_threads"]["id"] == "CONC-DOMAIN-META-SEMANTICS",
        "priority",
    ].item() == "low"

    xrefs = staging["concern_signal_xrefs"].to_dict(orient="records")
    assert {
        "id": "CTSX-SIG-CONC-TEST--CONC-ADAPTER-SPREADSHEET-BOUNDARY",
        "signal_id": "SIG-CONC-TEST",
        "concern_thread_id": "CONC-ADAPTER-SPREADSHEET-BOUNDARY",
        "signal_role": "test_role_roundtrip",
        "notes": "",
    } in xrefs
    assert {
        "id": "CTSX-SIG-CONC-TEST--CONC-DOMAIN-META-SEMANTICS",
        "signal_id": "SIG-CONC-TEST",
        "concern_thread_id": "CONC-DOMAIN-META-SEMANTICS",
        "signal_role": "driver",
        "notes": "existing note",
    } in xrefs
