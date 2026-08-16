"""E7 composition with the unchanged E5/E6 managed macro."""

from __future__ import annotations

import pandas as pd
import pytest

import spreadsheet_handling.application.orchestrator as orchestrator_module
from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.domain.ingress.structural_admission import (
    OrdinaryStructureAdmissionError,
)
from spreadsheet_handling.pipeline import (
    DescriptionAuthorizationError,
    LessTrustedDescriptionAuthorization,
    build_steps_from_config,
)
from spreadsheet_handling.pipeline.config import AppConfig, IOConfig, IOEndpoint
from spreadsheet_handling.pipeline.runner import run_app


pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _identity_policy() -> LessTrustedDescriptionAuthorization:
    return LessTrustedDescriptionAuthorization.from_mapping(
        {"registered_steps": {"identity": {}}}
    )


def _patch_managed_io(monkeypatch, frames):
    saved: list[dict] = []
    monkeypatch.setattr(orchestrator_module, "_load_frames", lambda *args, **kwargs: frames)
    monkeypatch.setattr(
        orchestrator_module,
        "_save_frames",
        lambda _out, result: saved.append(result),
    )
    return saved


@pytest.mark.parametrize("payload_provenance", ["trusted", "less_trusted"])
@pytest.mark.parametrize("description_mode", ["trusted", "less_trusted"])
def test_four_way_authority_matrix_preserves_valid_payload_behavior(
    monkeypatch, payload_provenance, description_mode
) -> None:
    del payload_provenance
    frames = {"Sheet": pd.DataFrame({"id": [1]})}
    saved = _patch_managed_io(monkeypatch, frames)
    steps = build_steps_from_config(
        [{"step": "identity"}],
        description_authorization=(
            _identity_policy() if description_mode == "less_trusted" else None
        ),
    )
    out = orchestrate(
        input={"kind": "json_dir", "path": "trusted-operator-input"},
        output={"kind": "json_dir", "path": "trusted-operator-output"},
        steps=steps,
    )
    assert out["Sheet"].to_dict(orient="records") == [{"id": 1}]
    assert saved == [out]


@pytest.mark.parametrize("payload_provenance", ["trusted", "less_trusted"])
@pytest.mark.parametrize("description_mode", ["trusted", "less_trusted"])
def test_four_way_authority_matrix_preserves_payload_rejection(
    monkeypatch, payload_provenance, description_mode
) -> None:
    del payload_provenance
    _patch_managed_io(monkeypatch, {"bad": object()})
    steps = build_steps_from_config(
        [{"step": "identity"}],
        description_authorization=(
            _identity_policy() if description_mode == "less_trusted" else None
        ),
    )
    with pytest.raises(OrdinaryStructureAdmissionError):
        orchestrate(
            input={"kind": "json_dir", "path": "trusted-operator-input"},
            output={"kind": "json_dir", "path": "trusted-operator-output"},
            steps=steps,
        )


def test_builder_denial_occurs_before_orchestrate_or_payload_load(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator_module,
        "orchestrate",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("orchestrate entered")),
    )
    with pytest.raises(DescriptionAuthorizationError) as excinfo:
        build_steps_from_config(
            [{"step": "validate"}], description_authorization=_identity_policy()
        )
    assert excinfo.value.kind == "forbidden_identifier"


def test_run_app_transports_policy_only_to_pipeline_construction(monkeypatch, tmp_path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "Sheet.json").write_text('[{"id": 1}]', encoding="utf-8")
    app = AppConfig(
        io=IOConfig(
            inputs={"primary": IOEndpoint(kind="json_dir", path=str(input_dir))},
            output=IOEndpoint(kind="json_dir", path=str(output_dir)),
        ),
        pipeline=[{"step": "identity"}],
    )
    frames, meta, issues = run_app(app, description_authorization=_identity_policy())
    assert frames["Sheet"].to_dict(orient="records") == [{"id": "1"}]
    assert meta == {}
    assert issues == []
    assert (output_dir / "Sheet.json").exists()


def test_run_app_pipeline_denial_precedes_managed_entry(monkeypatch, tmp_path) -> None:
    app = AppConfig(
        io=IOConfig(
            inputs={"primary": IOEndpoint(kind="json_dir", path=str(tmp_path / "input"))},
            output=IOEndpoint(kind="json_dir", path=str(tmp_path / "output")),
        ),
        pipeline=[{"step": "validate"}],
    )
    monkeypatch.setattr(
        orchestrator_module,
        "orchestrate",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("orchestrate entered")),
    )
    with pytest.raises(DescriptionAuthorizationError) as excinfo:
        run_app(app, description_authorization=_identity_policy())
    assert excinfo.value.kind == "forbidden_identifier"


def test_direct_bound_step_composition_remains_unchanged(monkeypatch) -> None:
    from spreadsheet_handling.pipeline.types import BoundStep

    frames = {"Sheet": pd.DataFrame({"id": [1]})}
    _patch_managed_io(monkeypatch, frames)
    calls: list[str] = []

    def direct(candidate):
        calls.append("direct")
        return candidate

    out = orchestrate(
        input={"kind": "json_dir", "path": "trusted-operator-input"},
        output={"kind": "json_dir", "path": "trusted-operator-output"},
        steps=[BoundStep(name="direct", config={}, fn=direct)],
    )
    assert calls == ["direct"]
    assert out["Sheet"].to_dict(orient="records") == [{"id": 1}]


def test_authorized_plugin_still_runs_through_managed_reestablishment(monkeypatch) -> None:
    target = "spreadsheet_handling.domain.pipeline_cleanup:execute_final_domain_cleanup"
    policy = LessTrustedDescriptionAuthorization.from_mapping(
        {"plugin_targets": [target]}
    )
    frames = {"Sheet": pd.DataFrame({"id": [1]})}
    _patch_managed_io(monkeypatch, frames)
    steps = build_steps_from_config(
        [{"step": "plugin", "dotted": target}],
        description_authorization=policy,
    )
    out = orchestrate(
        input={"kind": "json_dir", "path": "trusted-operator-input"},
        output={"kind": "json_dir", "path": "trusted-operator-output"},
        steps=steps,
    )
    assert out["Sheet"].to_dict(orient="records") == [{"id": 1}]
