from pathlib import Path

import pandas as pd
import pytest


TESTS_ROOT = Path(__file__).resolve().parent


def _item_rel_path(item: pytest.Item) -> Path:
    path = Path(str(getattr(item, "path", item.fspath))).resolve()
    try:
        return path.relative_to(TESTS_ROOT)
    except ValueError:
        return Path(path.name)


def _add_marker(item: pytest.Item, marker_name: str) -> None:
    if marker_name not in item.keywords:
        item.add_marker(getattr(pytest.mark, marker_name))


def _is_xlsx_ir_target(parts: tuple[str, ...], stem: str) -> bool:
    if "xlsx" in parts:
        return True
    if stem == "test_ods_xlsx_parity":
        return True
    if parts[:2] == ("integration", "spreadsheet_contract"):
        return True
    if parts[:2] == ("integration", "roundtrip") and stem == "test_parse_ir_roundtrip":
        return True
    if parts[:2] == ("integration", "pipeline") and stem == "test_ir_roundtrip_smoke":
        return True
    if parts[:2] == ("architecture", "spreadsheet_contract"):
        return True
    if parts[:2] == ("architecture", "current_state"):
        return True
    if parts[:2] == ("architecture", "parse_contract") and "xlsx" in stem:
        return True
    if parts[:2] == ("architecture", "semantic_invariants") and stem in {
        "test_ir_writepath_semantics",
        "test_spreadsheet_semantic_invariants",
    }:
        return True
    if parts[:2] == ("architecture", "dependency_guards") and stem in {
        "test_adapter_alignment",
        "test_ir_architecture_clarity",
    }:
        return True
    return stem == "test_spreadsheet_parse_contract"


def _is_ods_target(parts: tuple[str, ...], stem: str) -> bool:
    if "ods" in parts:
        return True
    if "odf" in stem:
        return True
    return stem.startswith("test_ods") or stem == "test_ods_xlsx_parity"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Apply the normalized marker vocabulary from path-first test topology.

    Physical placement remains the primary classification mechanism. These
    markers are a secondary execution axis used for Make targets and focused
    pytest slices.
    """
    for item in items:
        rel_path = _item_rel_path(item)
        parts = tuple(part.lower() for part in rel_path.parts)
        stem = rel_path.stem.lower()
        nodeid = item.nodeid.lower()

        if parts and parts[0] == "unit":
            _add_marker(item, "unit")
        elif parts and parts[0] == "integration":
            _add_marker(item, "integ")
        elif parts and parts[0] == "architecture":
            _add_marker(item, "arch")
            if "current_state" in parts:
                _add_marker(item, "current_state")
            else:
                _add_marker(item, "guardrail")
        elif parts and parts[0] == "legacy_pre_hex":
            _add_marker(item, "legacy")
            _add_marker(item, "prehex")

        if "smoke" in nodeid:
            _add_marker(item, "smoke")
        if _is_xlsx_ir_target(parts, stem):
            _add_marker(item, "xlsx_ir")
        if _is_ods_target(parts, stem):
            _add_marker(item, "ods")


@pytest.fixture
def tmpdir_path(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def df_products():
    return pd.DataFrame([
        {"id": "P-001", "name": "Alpha", "branch_id": "B-001"},
        {"id": "P-002", "name": "Beta",  "branch_id": "B-002"},
    ])


@pytest.fixture
def frames_minimal(df_products):
    return {
        "products": df_products.copy(),
        "branches": pd.DataFrame([
            {"branch_id": "B-001", "manager": "Alice"},
            {"branch_id": "B-002", "manager": "Bob"},
        ])
    }
