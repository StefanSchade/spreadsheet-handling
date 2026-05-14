"""Generic discriminator/context matrix roundtrip integration slice.

This intentionally uses the localized-resource example while keeping the
production mechanics generic: configured row keys, discriminator column,
matrix axis, and payload value column flow through existing primitives.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend
from spreadsheet_handling.pipeline import build_steps_from_config, run_pipeline


pytestmark = pytest.mark.ftr("FTR-LOCALIZED-RESOURCE-MATRIX-ROUNDTRIP-P4A")

_AXIS_COLUMNS = ["default", "product_a", "product_b"]
_LOCALIZED_FRAMES = {
    "de": {
        "tuple": "localized_values_de",
        "matrix": "localized_matrix_de",
        "view": "localized_edit_de",
        "payload": "localized_payload_de",
    },
    "en": {
        "tuple": "localized_values_en",
        "matrix": "localized_matrix_en",
        "view": "localized_edit_en",
        "payload": "localized_payload_en",
    },
}


def test_generic_discriminator_context_matrix_roundtrip_across_xlsx_and_ods(
    tmp_path: Path,
) -> None:
    source = _canonical_frames()
    forward = run_pipeline(source, build_steps_from_config(_forward_pipeline()))

    assert forward["localized_edit_de"].to_dict(orient="records") == [
        {
            "resource_type": "field_label",
            "description": "Amount label",
            "resource_key": "field.amount",
            "default": "Betrag",
            "product_a": "Betrag A",
            "product_b": "Betrag B",
        },
        {
            "resource_type": "field_label",
            "description": "Interest rate label",
            "resource_key": "field.rate",
            "default": "Zins",
            "product_a": "Zinssatz A",
            "product_b": "Zinssatz B",
        },
    ]

    for backend_name, write_read in _spreadsheet_roundtrips(tmp_path, forward).items():
        workbook_frames = write_read
        _simulate_business_edit(workbook_frames)

        recomposed = run_pipeline(
            workbook_frames,
            build_steps_from_config(_reverse_pipeline()),
        )

        pd.testing.assert_frame_equal(
            _ordered_identity(recomposed["localized_values"]),
            _ordered_identity(_expected_after_edit()),
            check_dtype=False,
            obj=f"{backend_name} recomposed canonical tuple frame",
        )
        assert "description" not in recomposed["localized_values"].columns
        assert "resource_type" not in recomposed["localized_values"].columns


def test_duplicate_tuple_identity_fails_before_matrix_projection() -> None:
    frames = _canonical_frames()
    duplicate = {
        "resource_key": "field.rate",
        "locale": "de",
        "context_id": "default",
        "text": "duplicate default",
    }
    frames["localized_values"] = pd.concat(
        [frames["localized_values"], pd.DataFrame([duplicate])],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match="Primary key values must be unique"):
        run_pipeline(frames, build_steps_from_config(_forward_pipeline()))


def _canonical_frames() -> dict[str, Any]:
    return {
        "resources": pd.DataFrame(
            [
                {
                    "resource_key": "field.rate",
                    "resource_type": "field_label",
                    "description": "Interest rate label",
                },
                {
                    "resource_key": "field.amount",
                    "resource_type": "field_label",
                    "description": "Amount label",
                },
            ]
        ),
        "locales": pd.DataFrame([{"locale": "de"}, {"locale": "en"}]),
        "resource_contexts": pd.DataFrame(
            [
                {"context_id": "default"},
                {"context_id": "product_a"},
                {"context_id": "product_b"},
            ]
        ),
        "localized_values": pd.DataFrame(
            [
                {
                    "resource_key": "field.rate",
                    "locale": "de",
                    "context_id": "default",
                    "text": "Zins",
                },
                {
                    "resource_key": "field.rate",
                    "locale": "de",
                    "context_id": "product_a",
                    "text": "Zinssatz A",
                },
                {
                    "resource_key": "field.rate",
                    "locale": "de",
                    "context_id": "product_b",
                    "text": "Zinssatz B",
                },
                {
                    "resource_key": "field.amount",
                    "locale": "de",
                    "context_id": "default",
                    "text": "Betrag",
                },
                {
                    "resource_key": "field.amount",
                    "locale": "de",
                    "context_id": "product_a",
                    "text": "Betrag A",
                },
                {
                    "resource_key": "field.amount",
                    "locale": "de",
                    "context_id": "product_b",
                    "text": "Betrag B",
                },
                {
                    "resource_key": "field.rate",
                    "locale": "en",
                    "context_id": "default",
                    "text": "Rate",
                },
                {
                    "resource_key": "field.rate",
                    "locale": "en",
                    "context_id": "product_a",
                    "text": "Rate A",
                },
                {
                    "resource_key": "field.rate",
                    "locale": "en",
                    "context_id": "product_b",
                    "text": "Rate B",
                },
                {
                    "resource_key": "field.amount",
                    "locale": "en",
                    "context_id": "default",
                    "text": "Amount",
                },
                {
                    "resource_key": "field.amount",
                    "locale": "en",
                    "context_id": "product_a",
                    "text": "Amount A",
                },
                {
                    "resource_key": "field.amount",
                    "locale": "en",
                    "context_id": "product_b",
                    "text": "Amount B",
                },
            ]
        ),
    }


def _forward_pipeline() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {
            "step": "validate_references",
            "mode": "fail",
            "rules": [
                {"type": "primary_key", "frame": "resources", "columns": ["resource_key"]},
                {"type": "primary_key", "frame": "locales", "columns": ["locale"]},
                {
                    "type": "primary_key",
                    "frame": "resource_contexts",
                    "columns": ["context_id"],
                },
                {
                    "type": "foreign_key",
                    "frame": "localized_values",
                    "columns": ["resource_key"],
                    "target": "resources",
                    "target_columns": ["resource_key"],
                    "allow_empty": False,
                },
                {
                    "type": "foreign_key",
                    "frame": "localized_values",
                    "columns": ["locale"],
                    "target": "locales",
                    "target_columns": ["locale"],
                    "allow_empty": False,
                },
                {
                    "type": "foreign_key",
                    "frame": "localized_values",
                    "columns": ["context_id"],
                    "target": "resource_contexts",
                    "target_columns": ["context_id"],
                    "allow_empty": False,
                },
                {
                    "type": "primary_key",
                    "frame": "localized_values",
                    "columns": ["resource_key", "locale", "context_id"],
                },
            ],
        },
        {
            "step": "split_by_discriminator",
            "source_frame": "localized_values",
            "discriminator_column": "locale",
            "target_pattern": "localized_values_{value}",
            "value_map": {
                "de": _LOCALIZED_FRAMES["de"]["tuple"],
                "en": _LOCALIZED_FRAMES["en"]["tuple"],
            },
        },
    ]
    for locale, names in _LOCALIZED_FRAMES.items():
        steps.extend(
            [
                {
                    "step": "contract_xref",
                    "relation": names["tuple"],
                    "output": names["matrix"],
                    "row_keys": ["resource_key"],
                    "column_key": "context_id",
                    "value": "text",
                    "column_keys": _AXIS_COLUMNS,
                    "name": f"localized_{locale}_contexts",
                },
                {
                    "step": "add_lookup_helpers",
                    "source": names["matrix"],
                    "lookup": "resources",
                    "output": names["view"],
                    "key": "resource_key",
                    "helpers": {"fields": ["resource_type", "description"]},
                    "order": {
                        "helper_position": "before_key",
                        "sort_by": ["resource_key"],
                    },
                    "missing": "fail",
                },
            ]
        )
    steps.append(
        {
            "step": "configure_workbook_view",
            "sheets": [
                {
                    "frame": _LOCALIZED_FRAMES["de"]["view"],
                    "sheet": _LOCALIZED_FRAMES["de"]["view"],
                    "editable_columns": _AXIS_COLUMNS,
                    "helper_columns": ["resource_type", "description"],
                },
                {
                    "frame": _LOCALIZED_FRAMES["en"]["view"],
                    "sheet": _LOCALIZED_FRAMES["en"]["view"],
                    "editable_columns": _AXIS_COLUMNS,
                    "helper_columns": ["resource_type", "description"],
                },
            ],
        }
    )
    return steps


def _reverse_pipeline() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for names in _LOCALIZED_FRAMES.values():
        steps.extend(
            [
                {
                    "step": "extract_frame",
                    "source": names["view"],
                    "output": names["payload"],
                    "columns": ["resource_key", *_AXIS_COLUMNS],
                },
                {
                    "step": "expand_xref",
                    "matrix": names["payload"],
                    "output": names["tuple"],
                    "row_keys": ["resource_key"],
                    "value_columns": _AXIS_COLUMNS,
                    "column_key": "context_id",
                    "value": "text",
                    "drop_empty": False,
                },
            ]
        )
    steps.extend(
        [
            {
                "step": "merge_by_discriminator",
                "target_frame": "localized_values",
                "discriminator_column": "locale",
                "source_pattern": "localized_values_{value}",
                "value_map": {
                    "de": _LOCALIZED_FRAMES["de"]["tuple"],
                    "en": _LOCALIZED_FRAMES["en"]["tuple"],
                },
                "column_order": ["resource_key", "locale", "context_id", "text"],
            },
            {
                "step": "validate_references",
                "mode": "fail",
                "rules": [
                    {
                        "type": "primary_key",
                        "frame": "localized_values",
                        "columns": ["resource_key", "locale", "context_id"],
                    }
                ],
            },
        ]
    )
    return steps


def _spreadsheet_roundtrips(
    tmp_path: Path,
    frames: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    xlsx_path = tmp_path / "localized-resource-matrix.xlsx"
    ods_path = tmp_path / "localized-resource-matrix.ods"

    ExcelBackend().write_multi(frames, str(xlsx_path))
    OdsBackend().write_multi(frames, str(ods_path))

    return {
        "xlsx": ExcelBackend().read_multi(str(xlsx_path), header_levels=1),
        "ods": OdsBackend().read_multi(str(ods_path), header_levels=1),
    }


def _simulate_business_edit(frames: dict[str, Any]) -> None:
    de = frames["localized_edit_de"]
    de.loc[de["resource_key"] == "field.amount", "product_b"] = "Betrag Kunde B"
    de.loc[de["resource_key"] == "field.amount", "description"] = "ignored helper edit"

    en = frames["localized_edit_en"]
    en.loc[en["resource_key"] == "field.rate", "product_a"] = "Hosted rate"
    en.loc[en["resource_key"] == "field.rate", "resource_type"] = "ignored_helper_type"


def _expected_after_edit() -> pd.DataFrame:
    expected = _canonical_frames()["localized_values"].copy()
    expected.loc[
        (expected["resource_key"] == "field.amount")
        & (expected["locale"] == "de")
        & (expected["context_id"] == "product_b"),
        "text",
    ] = "Betrag Kunde B"
    expected.loc[
        (expected["resource_key"] == "field.rate")
        & (expected["locale"] == "en")
        & (expected["context_id"] == "product_a"),
        "text",
    ] = "Hosted rate"
    return expected


def _ordered_identity(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(
        ["resource_key", "locale", "context_id"],
        kind="mergesort",
    ).reset_index(drop=True)
