"""Prove that Core consumes the exact standalone Workflow Coordinator."""

from __future__ import annotations

import ast
import importlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest


pytestmark = pytest.mark.ftr("FTR-AGENT-WORKFLOW-COORDINATOR-P5")

CORE_ROOT = Path(__file__).resolve().parents[3]
PIN = "0b5260f64f0e66211bca0e6634e76ad02506fc1d"
OLD_RESOURCE = "scripts/workflow_coordinator/resources/agent_operating_contract_v1.txt"
POLICIES = (
    CORE_ROOT
    / "docs/ai_info/workflows/dogfood/dmc_fk_c3_wi02/repository_policy.yaml",
    CORE_ROOT
    / "docs/ai_info/workflows/dogfood/ior04_formula_sink_capability/repository_policy.yaml",
)
REMOVED_PATHS = (
    "scripts/workflow_coordinator",
    "tests/unit/workflow_coordinator",
    "tests/architecture/dependency_guards/test_workflow_coordinator_relocatability.py",
    "tests/architecture/semantic_invariants/test_workflow_coordinator_replays.py",
    "tests/data/workflow_coordinator/slice5b_non_dmc.yaml",
    "tests/utils/workflow_coordinator.py",
)


def _distribution() -> importlib.metadata.Distribution:
    try:
        return importlib.metadata.distribution("workflow-coordinator")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("workflow-coordinator distribution is not installed locally")


def _live_python_files() -> tuple[Path, ...]:
    completed = subprocess.run(
        ("git", "-C", str(CORE_ROOT), "ls-files", "*.py"),
        check=True,
        text=True,
        capture_output=True,
    )
    paths = {CORE_ROOT / value for value in completed.stdout.splitlines()}
    paths.add(Path(__file__).resolve())
    return tuple(sorted(path for path in paths if path.exists()))


def _embedded_import_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_names = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]
    return [
        str(path.relative_to(CORE_ROOT))
        for name in imported_names
        if name == "scripts.workflow_coordinator"
        or name.startswith("scripts.workflow_coordinator.")
    ]


def _has_sibling_source_repair(path: Path) -> bool:
    if path.resolve() == Path(__file__).resolve():
        return False
    text = path.read_text(encoding="utf-8")
    mentions_path_repair = "sys.path" in text or "PYTHONPATH" in text
    mentions_wfc = "workflow-coordinator" in text or "workflow_coordinator" in text
    return mentions_path_repair and mentions_wfc


def test_embedded_implementation_and_generic_core_tests_are_absent() -> None:
    assert all(not (CORE_ROOT / path).exists() for path in REMOVED_PATHS)


def test_live_core_python_has_no_embedded_import_or_sibling_source_repair() -> None:
    paths = _live_python_files()
    violations = [
        violation
        for path in paths
        for violation in _embedded_import_violations(path)
    ]
    violations.extend(
        str(path.relative_to(CORE_ROOT)) for path in paths if _has_sibling_source_repair(path)
    )
    assert violations == []


def test_core_policies_and_resources_do_not_retain_embedded_a3() -> None:
    for policy in POLICIES:
        assert OLD_RESOURCE not in policy.read_text(encoding="utf-8")
    resources = [
        path
        for path in CORE_ROOT.rglob("agent_operating_contract_v1.txt")
        if ".venv" not in path.parts and "build" not in path.parts
    ]
    assert resources == []


def test_installed_distribution_has_exact_pep610_identity() -> None:
    distribution = _distribution()
    assert distribution.metadata["Name"] == "workflow-coordinator"
    assert distribution.version == "0.1.0"
    direct_url_text = distribution.read_text("direct_url.json")
    assert direct_url_text is not None
    direct_url = json.loads(direct_url_text)
    vcs_info = direct_url.get("vcs_info")
    assert vcs_info == {
        "commit_id": PIN,
        "requested_revision": PIN,
        "vcs": "git",
    }
    parsed = urlsplit(direct_url["url"].removeprefix("git+"))
    assert parsed.hostname == "github.com"
    assert parsed.path.lstrip("/") == "StefanSchade/workflow-coordinator.git"


def test_installed_import_and_wfc_entry_point_resolve_outside_core() -> None:
    distribution = _distribution()
    package = importlib.import_module("workflow_coordinator")
    package_path = Path(package.__file__).resolve()
    assert not package_path.is_relative_to(CORE_ROOT)
    assert "scripts/workflow_coordinator" not in package_path.as_posix()

    entry_points = [
        entry_point
        for entry_point in distribution.entry_points
        if entry_point.group == "console_scripts" and entry_point.name == "wfc"
    ]
    assert len(entry_points) == 1
    executable = Path(sys.executable).with_name("wfc")
    assert executable.is_file()
    result = subprocess.run(
        (str(executable), "--help"), text=True, capture_output=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
