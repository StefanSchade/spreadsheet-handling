from __future__ import annotations

from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.ftr("FTR-META-REGISTRY-P3H")


def _load_registry() -> dict:
    repo_root = Path(__file__).resolve().parents[3]
    registry_path = repo_root / "docs" / "internal_guide" / "architecture" / "meta_registry.yaml"
    with registry_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict)
    return loaded


def test_meta_registry_has_required_profile_fields():
    registry = _load_registry()
    entries = registry.get("entries")

    assert registry.get("registry_version") == 1
    assert isinstance(entries, list)
    assert entries

    required_fields = {
        "name",
        "layer",
        "meaning",
        "scope",
        "origin",
        "render_relevance",
        "persistence_behavior",
        "roundtrip_relevance",
        "producer",
        "consumer",
    }

    for entry in entries:
        assert required_fields <= set(entry)
        assert isinstance(entry["producer"], list)
        assert entry["producer"]
        assert isinstance(entry["consumer"], list)
        assert entry["consumer"]


def test_meta_registry_entry_names_are_unique():
    registry = _load_registry()
    names = [entry["name"] for entry in registry["entries"]]

    assert len(names) == len(set(names))


def test_meta_registry_seeds_current_known_entries():
    registry = _load_registry()
    names = {entry["name"] for entry in registry["entries"]}

    assert {
        "version",
        "author",
        "exported_at",
        "constraints",
        "freeze_header",
        "auto_filter",
        "header_fill_rgb",
        "helper_fill_rgb",
        "helper_prefix",
        "sheets",
        "workbook_meta_blob",
        "options",
        "__style",
        "__helper_cols",
        "__autofilter",
        "__freeze",
        "__autofilter_ref",
        "_hidden",
    } <= names
