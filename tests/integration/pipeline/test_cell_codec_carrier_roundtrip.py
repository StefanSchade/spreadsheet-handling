"""Cross-carrier roundtrip for the position-based Cell Codec contract.

Proves the string-oriented codec contract end to end: compact cells written
to XLSX and ODS decode back to identical structured string attributes,
including absent-value handling and numeric-looking string tokens, and no
``_meta.cell_codecs`` entries appear in any persisted carrier.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.pipeline.build import build_steps_from_config


pytestmark = pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")


CODEC_INTENT = {
    "participating_columns": ["delivery", "language", "auth"],
    "compact_column": "profile",
    "separator": "/",
    "absent_value": "-",
}

ROWS = [
    {"id": "p1", "delivery": "SaaS", "language": "JP", "auth": "OIDC"},
    {"id": "p2", "delivery": "AppStore", "language": "", "auth": "LDAP"},
    {"id": "p3", "delivery": "1", "language": "EN", "auth": "2"},
]


def _write_json_dir(path: Path, data: dict[str, list[dict]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, records in data.items():
        (path / f"{name}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )


@pytest.mark.parametrize("carrier", ["xlsx", "ods"])
def test_compact_cells_roundtrip_structured_attributes(
    tmp_path: Path, carrier: str
) -> None:
    in_dir = tmp_path / "in"
    _write_json_dir(in_dir, {"profiles": ROWS})
    artifact = tmp_path / f"out.{carrier}"

    orchestrate(
        input={"kind": "json_dir", "path": str(in_dir)},
        output={"kind": carrier, "path": str(artifact)},
        steps=build_steps_from_config(
            [
                {
                    "step": "encode_cell_values",
                    "source": "profiles",
                    "output": "profiles_compact",
                    "codec_intent": CODEC_INTENT,
                },
                {
                    "step": "configure_pipeline_cleanup",
                    "keep_frames": ["profiles_compact"],
                },
            ]
        ),
    )

    loaded = orchestrate(
        input={"kind": carrier, "path": str(artifact)},
        output={"kind": "discard", "path": "-"},
    )
    assert "cell_codecs" not in (loaded.get("_meta") or {})
    assert loaded["profiles_compact"]["profile"].tolist() == [
        "SaaS/JP/OIDC",
        "AppStore/-/LDAP",
        "1/EN/2",
    ]

    reimport_out = tmp_path / f"reimported_{carrier}"
    orchestrate(
        input={"kind": carrier, "path": str(artifact)},
        output={"kind": "json_dir", "path": str(reimport_out)},
        steps=build_steps_from_config(
            [
                {
                    "step": "decode_cell_values",
                    "source": "profiles_compact",
                    "output": "profiles",
                    "codec_intent": CODEC_INTENT,
                },
                {
                    "step": "configure_pipeline_cleanup",
                    "keep_frames": ["profiles"],
                },
            ]
        ),
    )

    recreated = json.loads(
        (reimport_out / "profiles.json").read_text(encoding="utf-8")
    )
    # String substrate: every structured attribute returns as a string; the
    # absent attribute decodes to "" (not null).
    by_id = {row["id"]: row for row in recreated}
    assert by_id["p1"] == {"id": "p1", "delivery": "SaaS", "language": "JP", "auth": "OIDC"}
    assert by_id["p2"] == {"id": "p2", "delivery": "AppStore", "language": "", "auth": "LDAP"}
    assert by_id["p3"] == {"id": "p3", "delivery": "1", "language": "EN", "auth": "2"}

    sidecar = yaml.safe_load((reimport_out / "_meta.yaml").read_text(encoding="utf-8")) or {}
    assert "cell_codecs" not in sidecar
