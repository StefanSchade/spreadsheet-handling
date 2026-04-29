"""Hardening checks for meta registry references and classifications.

These guards verify that reviewed registry entries resolve to permitted layers,
classifications, and code references instead of drifting silently.
"""
from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.ftr("FTR-META-REGISTRY-HARDENING-P3I")


def _load_registry() -> dict:
    repo_root = Path(__file__).resolve().parents[3]
    registry_path = repo_root / "docs" / "internal_guide" / "architecture" / "meta_registry.yaml"
    with registry_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict)
    return loaded


def _resolve_code_reference(reference: str) -> bool:
    parts = ["spreadsheet_handling", *reference.split(".")]

    for module_end in range(len(parts), 0, -1):
        module_name = ".".join(parts[:module_end])
        try:
            obj = import_module(module_name)
        except ModuleNotFoundError as exc:
            missing_name = exc.name or ""
            if missing_name and not module_name.startswith(missing_name):
                raise
            continue

        for attr in parts[module_end:]:
            if not hasattr(obj, attr):
                return False
            obj = getattr(obj, attr)
        return True

    return False


def test_meta_registry_entries_use_allowed_layers_and_classifications():
    registry = _load_registry()
    maintenance_contract = registry["maintenance_contract"]
    allowed_layers = set(maintenance_contract["allowed_layers"])
    allowed_classifications = set(maintenance_contract["allowed_classifications"])

    for entry in registry["entries"]:
        assert entry["layer"] in allowed_layers
        assert entry["classification"] in allowed_classifications

        if entry["classification"] == "canonical_meta":
            assert entry["layer"] == "meta_canonical"
        else:
            assert entry["layer"] == "meta_rendering"


def test_meta_registry_current_seed_profiles_stay_explicit():
    registry = _load_registry()
    expected_profiles = {
        "version": ("meta_canonical", "canonical_meta"),
        "author": ("meta_canonical", "canonical_meta"),
        "exported_at": ("meta_canonical", "canonical_meta"),
        "sheets": ("meta_canonical", "canonical_meta"),
        "freeze_header": ("meta_canonical", "canonical_meta"),
        "auto_filter": ("meta_canonical", "canonical_meta"),
        "header_fill_rgb": ("meta_canonical", "canonical_meta"),
        "helper_fill_rgb": ("meta_canonical", "canonical_meta"),
        "helper_prefix": ("meta_canonical", "canonical_meta"),
        "helper_policies": ("meta_canonical", "canonical_meta"),
        "constraints": ("meta_canonical", "canonical_meta"),
        "legend_blocks": ("meta_canonical", "canonical_meta"),
        "xref_crosstable": ("meta_canonical", "canonical_meta"),
        "cell_codecs": ("meta_canonical", "canonical_meta"),
        "compact_multiaxis": ("meta_canonical", "canonical_meta"),
        "workbook_meta_blob": ("meta_rendering", "carrier_artifact"),
        "options": ("meta_rendering", "derived_operational_view"),
        "__style": ("meta_rendering", "derived_operational_view"),
        "__helper_cols": ("meta_rendering", "derived_operational_view"),
        "__autofilter": ("meta_rendering", "derived_operational_view"),
        "__freeze": ("meta_rendering", "derived_operational_view"),
        "__autofilter_ref": ("meta_rendering", "read_path_hint"),
        "__legend_blocks": ("meta_rendering", "read_path_hint"),
        "_hidden": ("meta_rendering", "carrier_artifact"),
    }

    actual_profiles = {
        entry["name"]: (entry["layer"], entry["classification"])
        for entry in registry["entries"]
    }

    assert actual_profiles == expected_profiles


def test_meta_registry_reference_lists_are_nonempty_and_unique_per_entry():
    registry = _load_registry()

    for entry in registry["entries"]:
        for field_name in ("producer", "consumer"):
            refs = entry[field_name]
            assert refs
            assert len(refs) == len(set(refs))
            assert all(isinstance(ref, str) and ref.strip() for ref in refs)


def test_meta_registry_code_references_resolve_or_are_explicitly_narrative():
    registry = _load_registry()
    approved_narrative_references = set(
        registry["reference_conventions"]["approved_narrative_references"]
    )

    for entry in registry["entries"]:
        for field_name in ("producer", "consumer"):
            for reference in entry[field_name]:
                if " " in reference:
                    assert reference in approved_narrative_references
                    continue

                assert _resolve_code_reference(reference), (
                    f"Unresolvable {field_name} reference {reference!r} "
                    f"for entry {entry['name']!r}"
                )
