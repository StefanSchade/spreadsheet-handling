"""Black-box Core consumer acceptance through the installed ``wfc`` CLI."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.ftr("FTR-AGENT-WORKFLOW-COORDINATOR-P5")

CORE_ROOT = Path(__file__).resolve().parents[3]
DOGFOOD_ROOT = CORE_ROOT / "docs/ai_info/workflows/dogfood"
BUNDLES = ("dmc_fk_c3_wi02", "ior04_formula_sink_capability")
DMC_ARTIFACT = (
    "docs/warm_storage/global_reviews/"
    "domain_fk_reference_helper_family_cycle3_missing_target_id_identity_assessment_2026-09-11.adoc"
)


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repository), *args),
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def _wfc() -> str:
    try:
        importlib.metadata.distribution("workflow-coordinator")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("workflow-coordinator distribution is not installed locally")
    executable = Path(sys.executable).with_name("wfc")
    assert executable.is_file()
    return str(executable)


def _copy_core_file(repository: Path, relative_path: str) -> None:
    source = CORE_ROOT / relative_path
    assert source.is_file(), relative_path
    destination = repository / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _seed_repository(tmp_path: Path, bundle_name: str) -> tuple[Path, dict[str, str]]:
    repository = tmp_path / f"{bundle_name}-consumer-repository"
    repository.mkdir()
    subprocess.run(("git", "init", str(repository)), check=True, capture_output=True)
    _git(repository, "config", "user.email", "core-consumer@example.invalid")
    _git(repository, "config", "user.name", "Core consumer fixture")

    bundle_relative = f"docs/ai_info/workflows/dogfood/{bundle_name}"
    paths = {
        "work_item": f"{bundle_relative}/work_item.yaml",
        "profile": f"{bundle_relative}/profile.yaml",
        "policy": f"{bundle_relative}/repository_policy.yaml",
        "components": f"{bundle_relative}/components.yaml",
        "task": f"{bundle_relative}/task.txt",
    }
    for path in paths.values():
        _copy_core_file(repository, path)

    manifest = yaml.safe_load((repository / paths["components"]).read_text(encoding="utf-8"))
    for reference in manifest["components"].values():
        _copy_core_file(repository, reference["path"])

    if bundle_name == "dmc_fk_c3_wi02":
        # The DMC Hop must create this durable artifact; the seed must not contain it.
        assert not (CORE_ROOT / DMC_ARTIFACT).exists(), (
            "DMC durable artifact unexpectedly exists in live Core; "
            "this fixture proves creation, not overwrite"
        )
        assert not (repository / DMC_ARTIFACT).exists()

    _git(repository, "add", ".")
    _git(repository, "commit", "-m", f"test: seed real Core {bundle_name} bundle")
    return repository, paths


def _command(
    repository: Path,
    state_root: Path,
    paths: dict[str, str],
    executable: Path,
    *,
    durable_artifact: str | None = None,
) -> list[str]:
    command = [
        _wfc(),
        "--repository",
        str(repository),
        "--state-root",
        str(state_root),
        "--expected-head",
        _git(repository, "rev-parse", "HEAD"),
        "--work-item",
        paths["work_item"],
        "--profile",
        paths["profile"],
        "--policy",
        paths["policy"],
        "--components",
        paths["components"],
        "--task",
        paths["task"],
        "--timeout-seconds",
        "10",
        "--executable",
        str(executable),
    ]
    if durable_artifact is not None:
        command.extend(("--durable-artifact", durable_artifact))
    return command


def _run(command: list[str], blocker_dir: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PATH"] = f"{blocker_dir}{os.pathsep}{environment['PATH']}"
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=60,
        env=environment,
    )


@pytest.fixture
def provider_block(tmp_path: Path) -> tuple[Path, Path]:
    blocker_dir = tmp_path / "provider-block"
    sentinel = tmp_path / "provider-invoked"
    blocker_dir.mkdir()
    body = f"#!/bin/sh\nprintf invoked > {sentinel!s}\nexit 97\n"
    for name in ("codex", "claude"):
        path = blocker_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    yield blocker_dir, sentinel
    assert not sentinel.exists(), "a real-provider command path was invoked"


@pytest.fixture(autouse=True)
def live_core_remains_read_only() -> None:
    before_head = _git(CORE_ROOT, "rev-parse", "HEAD")
    before_status = _git(CORE_ROOT, "status", "--porcelain=v1", "-uall")
    yield
    assert _git(CORE_ROOT, "rev-parse", "HEAD") == before_head
    assert _git(CORE_ROOT, "status", "--porcelain=v1", "-uall") == before_status


@pytest.mark.parametrize("bundle_name", BUNDLES)
def test_real_core_bundle_rejection_has_no_state(
    tmp_path: Path, provider_block: tuple[Path, Path], bundle_name: str
) -> None:
    blocker_dir, _ = provider_block
    repository, paths = _seed_repository(tmp_path, bundle_name)
    policy_path = repository / paths["policy"]
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["governance_paths"] = ["intentionally/rejected"]
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    _git(repository, "add", paths["policy"])
    _git(repository, "commit", "-m", "test: reject governing inputs")

    state_root = tmp_path / f"{bundle_name}-rejected-state"
    result = _run(_command(repository, state_root, paths, blocker_dir / "codex"), blocker_dir)
    assert result.returncode == 2, result.stderr
    assert not state_root.exists()


@pytest.mark.parametrize("bundle_name", BUNDLES)
def test_real_core_bundle_admission_records_governance_and_evidence(
    tmp_path: Path, provider_block: tuple[Path, Path], bundle_name: str
) -> None:
    blocker_dir, _ = provider_block
    repository, paths = _seed_repository(tmp_path, bundle_name)
    failing_fake = tmp_path / f"{bundle_name}-admitted-fake"
    failing_fake.write_text("#!/bin/sh\nexit 23\n", encoding="utf-8")
    failing_fake.chmod(0o755)
    state_root = tmp_path / f"{bundle_name}-admitted-state"

    result = _run(
        _command(
            repository,
            state_root,
            paths,
            failing_fake,
            durable_artifact=(
                DMC_ARTIFACT if bundle_name == "dmc_fk_c3_wi02" else None
            ),
        ),
        blocker_dir,
    )
    assert result.returncode == 1, result.stderr
    plan = json.loads((state_root / "operator-plan.json").read_text(encoding="utf-8"))
    assert plan["inputs"] == {**paths, "pinned_revision": _git(repository, "rev-parse", "HEAD")}
    assert set(plan["governing_inputs"]) == set(paths.values()) | {
        value["path"]
        for value in yaml.safe_load(
            (repository / paths["components"]).read_text(encoding="utf-8")
        )["components"].values()
    }
    assert all(plan["governing_inputs"].values())
    assert [item["command_name"] for item in plan["evidence"]["selected_commands"]] == [
        "diff_hygiene",
        "git_version",
    ]
    assert all(item["argv_digest"] for item in plan["evidence"]["selected_commands"])
    assert plan["agent_operating_contract"]["sha256"]


def test_dmc_bundle_completes_one_truthful_coordinator_owned_hop(
    tmp_path: Path, provider_block: tuple[Path, Path]
) -> None:
    blocker_dir, _ = provider_block
    repository, paths = _seed_repository(tmp_path, "dmc_fk_c3_wi02")
    fake = tmp_path / "fake-dmc-agent"
    fake.write_text(
        """#!/usr/bin/env python3
import json
import pathlib
import sys

args = sys.argv[1:]
repository = pathlib.Path(args[args.index("--cd") + 1])
output = pathlib.Path(args[args.index("--output-last-message") + 1])
prompt = sys.stdin.read()
artifact = repository / """ + repr(DMC_ARTIFACT) + """
artifact.parent.mkdir(parents=True, exist_ok=True)
artifact.write_text("= Disposable DMC assessment\\n\\nNO SAFE SLICE SELECTED.\\n", encoding="utf-8")

def fact(name):
    return prompt.split(name + "=", 1)[1].split("\\n", 1)[0]

output.write_text(json.dumps({
    "schema_version": 1,
    "run_id": fact("run_id"),
    "hop_id": fact("hop_id"),
    "invocation_id": fact("invocation_id"),
    "result": {
        "schema_version": 1,
        "outcome": "completed",
        "requested_route": "complete",
        "scope_changed": False,
        "requires_human": False,
        "escalation": None,
        "findings": [],
        "claimed_commits": [],
        "commit_intent": {
            "paths": [""" + repr(DMC_ARTIFACT) + """],
            "subject": "docs(domain): DMC-FK-C3-WI02 H001 assess missing target IDs"
        },
        "evidence_refs": ["diff_hygiene", "git_version"],
        "summary": "Disposable Core consumer proof completed."
    }
}), encoding="utf-8")
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    state_root = tmp_path / "dmc-completed-state"
    seed_head = _git(repository, "rev-parse", "HEAD")

    result = _run(
        _command(
            repository,
            state_root,
            paths,
            fake,
            durable_artifact=DMC_ARTIFACT,
        ),
        blocker_dir,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads((state_root / "operator-summary.json").read_text(encoding="utf-8"))
    assert summary["run_status"] == "completed"
    assert summary["hop_used"] == 1
    assert summary["worktree_clean"] is True
    assert summary["changed_paths"] == [DMC_ARTIFACT]
    assert len(summary["commits"]) == 1
    observations = summary["execution_evidence"][0]["trusted_observations"]
    assert [(item["command_name"], item["status"]) for item in observations] == [
        ("diff_hygiene", "pass"),
        ("git_version", "pass"),
    ]
    assert _git(repository, "rev-parse", "HEAD") != seed_head
    assert _git(repository, "log", "-1", "--format=%s") == (
        "docs(domain): DMC-FK-C3-WI02 H001 assess missing target IDs"
    )
    assert _git(repository, "status", "--porcelain") == ""
