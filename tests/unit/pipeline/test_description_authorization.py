"""Phase-E E7 less-trusted description authorization evidence."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pandas as pd
import pytest

import spreadsheet_handling.pipeline.build as build_module
import spreadsheet_handling.pipeline.description_authorization as authorization_module
import spreadsheet_handling.pipeline.steps as steps_module
from spreadsheet_handling.pipeline import (
    DescriptionAuthorizationError,
    LessTrustedDescriptionAuthorization,
    build_steps_from_config,
    build_steps_from_yaml,
    run_pipeline,
)
from spreadsheet_handling.pipeline.registry import REGISTRY


pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")

_PLUGIN = "spreadsheet_handling.domain.pipeline_cleanup:execute_final_domain_cleanup"
_PLUGIN_DOT = "spreadsheet_handling.domain.pipeline_cleanup.execute_final_domain_cleanup"


def _policy(
    *,
    registered_steps: dict | None = None,
    plugin_targets: list[str] | None = None,
) -> LessTrustedDescriptionAuthorization:
    return LessTrustedDescriptionAuthorization.from_mapping(
        {
            "registered_steps": registered_steps or {},
            "plugin_targets": plugin_targets or [],
        }
    )


def _assert_error(kind: str, callback) -> DescriptionAuthorizationError:
    with pytest.raises(DescriptionAuthorizationError) as excinfo:
        callback()
    assert excinfo.value.kind == kind
    return excinfo.value


def test_empty_policy_denies_registry_membership_alone() -> None:
    _assert_error(
        "forbidden_identifier",
        lambda: build_steps_from_config(
            [{"step": "identity"}], description_authorization=_policy()
        ),
    )


def test_exact_registered_name_allow_does_not_allow_adjacent_name() -> None:
    policy = _policy(registered_steps={"identity": {}})
    [step] = build_steps_from_config(
        [{"step": "identity"}], description_authorization=policy
    )
    assert step.name == "identity"
    _assert_error(
        "forbidden_identifier",
        lambda: build_steps_from_config(
            [{"step": "validate"}], description_authorization=policy
        ),
    )


@pytest.mark.parametrize(
    "mapping",
    [
        {"unknown": True},
        {"registered_steps": []},
        {"registered_steps": {"missing": {}}},
        {"registered_steps": {"plugin": {}}},
        {"registered_steps": {"identity": {"output_roots": ["/tmp"]}}},
        {"registered_steps": {"write_structured_yaml": {}}},
        {"registered_steps": {"write_structured_yaml": {"output_roots": []}}},
        {"registered_steps": {"write_structured_yaml": {"output_roots": ["relative"]}}},
        {
            "registered_steps": {
                "write_artifact_manifest": {"allow_checksum_reads": True}
            }
        },
        {
            "registered_steps": {
                "write_artifact_manifest": {
                    "output_roots": ["/tmp"],
                    "allow_checksum_reads": "yes",
                }
            }
        },
        {"plugin_targets": {_PLUGIN: {"constraints": {}}}},
        {"plugin_targets": ["bad target"]},
        {"plugin_targets": ["spreadsheet_handling.domain.ingress:run_domain_ingress"]},
        {"plugin_targets": [_PLUGIN, _PLUGIN_DOT]},
    ],
)
def test_closed_policy_grammar_rejects_invalid_shapes(mapping) -> None:
    _assert_error(
        "invalid_policy",
        lambda: LessTrustedDescriptionAuthorization.from_mapping(mapping),
    )


def test_duplicate_canonical_output_roots_reject(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    _assert_error(
        "invalid_policy",
        lambda: _policy(
            registered_steps={
                "write_structured_yaml": {
                    "output_roots": [str(root), str(root / ".")]
                }
            }
        ),
    )


def test_policy_copies_all_caller_owned_aliases(tmp_path: Path) -> None:
    root = tmp_path / "root"
    other = tmp_path / "other"
    roots = [str(root.resolve())]
    constraints = {"output_roots": roots}
    registered = {"identity": {}, "write_structured_yaml": constraints}
    targets = [_PLUGIN]
    source = {"registered_steps": registered, "plugin_targets": targets}
    policy = LessTrustedDescriptionAuthorization.from_mapping(source)

    registered["validate"] = {}
    roots.append(str(other.resolve()))
    constraints["unknown"] = True
    targets.append("spreadsheet_handling.domain.pipeline_cleanup:configure_pipeline_cleanup")
    source["registered_steps"] = {}

    [identity] = build_steps_from_config(
        [{"step": "identity"}], description_authorization=policy
    )
    assert identity.name == "identity"
    _assert_error(
        "forbidden_identifier",
        lambda: build_steps_from_config(
            [{"step": "validate"}], description_authorization=policy
        ),
    )
    _assert_error(
        "forbidden_resource_selector",
        lambda: build_steps_from_config(
            [
                {
                    "step": "write_structured_yaml",
                    "output_dir": str(other),
                    "files": [{"path": "out.yml"}],
                }
            ],
            description_authorization=policy,
        ),
    )
    _assert_error(
        "forbidden_identifier",
        lambda: build_steps_from_config(
            [
                {
                    "step": "plugin",
                    "dotted": (
                        "spreadsheet_handling.domain.pipeline_cleanup:"
                        "configure_pipeline_cleanup"
                    ),
                }
            ],
            description_authorization=policy,
        ),
    )


def test_mapping_proxy_policy_is_copied_not_merely_wrapped() -> None:
    nested = {"identity": {}}
    backing = {"registered_steps": nested}
    policy = LessTrustedDescriptionAuthorization.from_mapping(MappingProxyType(backing))
    nested["validate"] = {}
    backing["plugin_targets"] = [_PLUGIN]

    [step] = build_steps_from_config(
        [{"step": "identity"}], description_authorization=policy
    )
    assert step.name == "identity"
    _assert_error(
        "forbidden_identifier",
        lambda: build_steps_from_config(
            [{"step": "validate"}], description_authorization=policy
        ),
    )


def test_builder_requires_exact_authorization_value_type() -> None:
    _assert_error(
        "invalid_policy",
        lambda: build_steps_from_config(
            [{"step": "identity"}], description_authorization={}  # type: ignore[arg-type]
        ),
    )


def test_public_policy_value_is_frozen_and_narrowly_exported() -> None:
    import spreadsheet_handling as top_level
    import spreadsheet_handling.pipeline as pipeline

    policy = _policy()
    with pytest.raises((AttributeError, TypeError)):
        policy._plugin_targets = frozenset({_PLUGIN})
    assert pipeline.LessTrustedDescriptionAuthorization is LessTrustedDescriptionAuthorization
    assert pipeline.DescriptionAuthorizationError is DescriptionAuthorizationError
    assert not hasattr(top_level, "LessTrustedDescriptionAuthorization")
    assert not hasattr(top_level, "DescriptionAuthorizationError")


def test_current_registry_has_exactly_one_explicit_e7_classification() -> None:
    assert set(authorization_module._REGISTERED_STEP_CLASSIFICATIONS) == set(REGISTRY) - {
        "plugin"
    }
    assert set(authorization_module._REGISTERED_STEP_CLASSIFICATIONS.values()) == {
        "ordinary",
        "inline-overrides-only",
        "root-contained-writer",
        "artifact-manifest",
    }


def test_future_registry_entry_is_not_implicitly_authorizable(monkeypatch) -> None:
    monkeypatch.setitem(REGISTRY, "future_step", steps_module.make_identity_step)
    _assert_error(
        "invalid_policy",
        lambda: _policy(registered_steps={"future_step": {}}),
    )
    _assert_error(
        "forbidden_capability",
        lambda: build_steps_from_config(
            [{"step": "future_step"}], description_authorization=_policy()
        ),
    )


def test_denied_plugin_reaches_no_resolver_factory_binding_or_invocation(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("denied plugin activated")

    monkeypatch.setattr(build_module, "resolve_registration", forbidden)
    monkeypatch.setattr(steps_module, "resolve_configuration_callable", forbidden)
    monkeypatch.setattr(steps_module, "make_plugin_step", forbidden)

    _assert_error(
        "forbidden_identifier",
        lambda: build_steps_from_config(
            [{"step": "plugin", "dotted": _PLUGIN}],
            description_authorization=_policy(),
        ),
    )


def test_denied_direct_colon_never_calls_resolve_registration(monkeypatch) -> None:
    monkeypatch.setattr(
        build_module,
        "resolve_registration",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("resolver called")),
    )
    _assert_error(
        "forbidden_capability",
        lambda: build_steps_from_config(
            [{"step": "external.module:make_step"}],
            description_authorization=_policy(),
        ),
    )


def test_denied_nested_route_imports_neither_outer_nor_nested(monkeypatch) -> None:
    monkeypatch.setattr(
        build_module,
        "resolve_registration",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("outer resolved")),
    )
    monkeypatch.setattr(
        steps_module,
        "resolve_configuration_callable",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("nested resolved")),
    )
    _assert_error(
        "forbidden_capability",
        lambda: build_steps_from_config(
            [
                {
                    "step": "spreadsheet_handling.pipeline.steps:make_frames_target_step",
                    "target": "external.module:target",
                    "name": "nested",
                }
            ],
            description_authorization=_policy(),
        ),
    )


def test_denied_registered_step_reaches_no_registration_or_internal_target(monkeypatch) -> None:
    monkeypatch.setattr(
        build_module,
        "resolve_registration",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("registration reached")),
    )
    monkeypatch.setattr(
        steps_module,
        "resolve_configuration_callable",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("target reached")),
    )
    _assert_error(
        "forbidden_identifier",
        lambda: build_steps_from_config(
            [{"step": "bootstrap_meta"}], description_authorization=_policy()
        ),
    )


def test_authorized_registered_step_authorizes_before_internal_target_and_ignores_plugin_policy(
    monkeypatch,
) -> None:
    events: list[str] = []
    real_authorize = authorization_module._authorize_step_spec
    real_registration = build_module.resolve_registration
    real_resolve = steps_module.resolve_configuration_callable

    def authorize(*args, **kwargs):
        events.append("authorize")
        return real_authorize(*args, **kwargs)

    def registration(step_id):
        events.append("registration")
        return real_registration(step_id)

    def resolve(target):
        events.append("internal_target")
        return real_resolve(target)

    monkeypatch.setattr(build_module, "_authorize_step_spec", authorize)
    monkeypatch.setattr(build_module, "resolve_registration", registration)
    monkeypatch.setattr(steps_module, "resolve_configuration_callable", resolve)

    [step] = build_steps_from_config(
        [{"step": "bootstrap_meta"}],
        description_authorization=_policy(registered_steps={"bootstrap_meta": {}}),
    )
    assert step.name == "bootstrap_meta"
    assert events == ["authorize", "registration", "internal_target"]


def test_authorized_plugin_resolves_only_after_allow_and_invokes_only_at_execution(
    monkeypatch,
) -> None:
    events: list[str] = []

    def target(frames, **kwargs):
        events.append("invoke")
        return frames

    def resolver(reference):
        events.append("resolve")
        assert reference == _PLUGIN_DOT
        return target

    monkeypatch.setattr(steps_module, "resolve_configuration_callable", resolver)
    [step] = build_steps_from_config(
        [{"step": "plugin", "dotted": _PLUGIN_DOT}],
        description_authorization=_policy(plugin_targets=[_PLUGIN]),
    )
    assert events == ["resolve"]
    assert step({}) == {}
    assert events == ["resolve", "invoke"]


def test_plugin_colon_and_final_dot_spellings_share_authority() -> None:
    policy = _policy(plugin_targets=[_PLUGIN])
    [step] = build_steps_from_config(
        [{"step": "plugin", "dotted": _PLUGIN_DOT}],
        description_authorization=policy,
    )
    assert step.name == "plugin"


def test_plugin_reexport_does_not_inherit_authority(monkeypatch) -> None:
    monkeypatch.setattr(
        steps_module,
        "resolve_configuration_callable",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("imported")),
    )
    _assert_error(
        "forbidden_identifier",
        lambda: build_steps_from_config(
            [
                {
                    "step": "plugin",
                    "dotted": (
                        "spreadsheet_handling.application.orchestrator:"
                        "execute_final_domain_cleanup"
                    ),
                }
            ],
            description_authorization=_policy(plugin_targets=[_PLUGIN]),
        ),
    )


@pytest.mark.parametrize(
    "dotted",
    ["bad target", "external.module::target", "spreadsheet_handling.domain.ingress:run_domain_ingress"],
)
def test_malformed_or_blocked_plugin_rejects_before_import(dotted, monkeypatch) -> None:
    monkeypatch.setattr(
        steps_module,
        "resolve_configuration_callable",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("imported")),
    )
    _assert_error(
        "malformed_description",
        lambda: build_steps_from_config(
            [{"step": "plugin", "dotted": dotted}],
            description_authorization=_policy(),
        ),
    )


def test_reserved_step_shell_policy_key_rejects_but_same_plugin_arg_key_is_data() -> None:
    policy = _policy(registered_steps={"identity": {}}, plugin_targets=[_PLUGIN])
    _assert_error(
        "invalid_policy_request",
        lambda: build_steps_from_config(
            [{"step": "identity", "description_authorization": None}],
            description_authorization=policy,
        ),
    )
    [step] = build_steps_from_config(
        [
            {
                "step": "plugin",
                "dotted": _PLUGIN,
                "args": {"description_authorization": "target-local"},
            }
        ],
        description_authorization=policy,
    )
    assert step.name == "plugin"


class _Hostile:
    calls = 0

    def __iter__(self):
        type(self).calls += 1
        raise AssertionError

    def __repr__(self):
        type(self).calls += 1
        raise AssertionError

    def __str__(self):
        type(self).calls += 1
        raise AssertionError

    def __deepcopy__(self, memo):
        type(self).calls += 1
        raise AssertionError


class _HostileList(list):
    calls = 0

    def __iter__(self):
        type(self).calls += 1
        raise AssertionError


def test_unsupported_objects_fail_without_invoking_python_hooks() -> None:
    _Hostile.calls = 0
    _assert_error(
        "malformed_description",
        lambda: build_steps_from_config(
            [{"step": "identity", "value": _Hostile()}],
            description_authorization=_policy(registered_steps={"identity": {}}),
        ),
    )
    assert _Hostile.calls == 0

    _HostileList.calls = 0
    _assert_error(
        "malformed_description",
        lambda: build_steps_from_config(
            _HostileList([{"step": "identity"}]),
            description_authorization=_policy(registered_steps={"identity": {}}),
        ),
    )
    assert _HostileList.calls == 0


def test_trusted_builder_keeps_general_iterable_compatibility() -> None:
    specs = ({"step": "identity"} for _ in range(1))
    [step] = build_steps_from_config(specs)
    assert step.name == "identity"


def test_description_snapshot_prevents_step_name_swap(monkeypatch) -> None:
    source = [{"step": "identity"}]
    real_authorize = build_module._authorize_step_spec

    def mutate_then_authorize(*args, **kwargs):
        source[0]["step"] = "validate"
        return real_authorize(*args, **kwargs)

    monkeypatch.setattr(build_module, "_authorize_step_spec", mutate_then_authorize)
    [step] = build_steps_from_config(
        source,
        description_authorization=_policy(registered_steps={"identity": {}}),
    )
    assert step.name == "identity"


def test_description_snapshot_prevents_plugin_target_swap(monkeypatch) -> None:
    source = [{"step": "plugin", "dotted": _PLUGIN}]
    real_authorize = build_module._authorize_step_spec

    def mutate_then_authorize(*args, **kwargs):
        source[0]["dotted"] = "external.module:other"
        return real_authorize(*args, **kwargs)

    monkeypatch.setattr(build_module, "_authorize_step_spec", mutate_then_authorize)
    [step] = build_steps_from_config(
        source, description_authorization=_policy(plugin_targets=[_PLUGIN])
    )
    assert step.config["dotted"] == _PLUGIN


def test_description_snapshot_prevents_root_and_static_path_swap(tmp_path, monkeypatch) -> None:
    root = tmp_path / "allowed"
    source = [
        {
            "step": "write_structured_yaml",
            "output_dir": str(root),
            "files": [{"path": "inside.yml"}],
        }
    ]
    real_authorize = build_module._authorize_step_spec

    def mutate_then_authorize(*args, **kwargs):
        source[0]["output_dir"] = str(tmp_path / "outside")
        source[0]["files"][0]["path"] = "../outside.yml"
        return real_authorize(*args, **kwargs)

    monkeypatch.setattr(build_module, "_authorize_step_spec", mutate_then_authorize)
    [step] = build_steps_from_config(
        source,
        description_authorization=_policy(
            registered_steps={
                "write_structured_yaml": {"output_roots": [str(root.resolve())]}
            }
        ),
    )
    assert step.config["output_dir"] == str(root.resolve())
    assert step.config["files"][0]["path"] == "inside.yml"


def test_description_snapshot_prevents_checksum_swap(monkeypatch) -> None:
    source = [{"step": "write_artifact_manifest", "reports": [], "checksum": None}]
    real_authorize = build_module._authorize_step_spec

    def mutate_then_authorize(*args, **kwargs):
        source[0]["checksum"] = "sha256"
        return real_authorize(*args, **kwargs)

    monkeypatch.setattr(build_module, "_authorize_step_spec", mutate_then_authorize)
    [step] = build_steps_from_config(
        source,
        description_authorization=_policy(
            registered_steps={"write_artifact_manifest": {}}
        ),
    )
    assert step.config["checksum"] is None


def test_less_trusted_yaml_builder_uses_same_authorization(tmp_path: Path) -> None:
    path = tmp_path / "pipeline.yml"
    path.write_text("pipeline:\n  - step: identity\n", encoding="utf-8")
    [step] = build_steps_from_yaml(
        str(path),
        description_authorization=_policy(registered_steps={"identity": {}}),
    )
    assert step.name == "identity"


def test_trusted_mode_preserves_registered_plugin_direct_colon_and_nested_target() -> None:
    steps = build_steps_from_config(
        [
            {"step": "identity"},
            {"step": "plugin", "dotted": _PLUGIN},
            {"step": "spreadsheet_handling.pipeline.steps:make_identity_step"},
            {
                "step": "spreadsheet_handling.pipeline.steps:make_frames_target_step",
                "target": _PLUGIN,
                "name": "nested",
            },
        ]
    )
    frames = {"data": pd.DataFrame({"id": [1]})}
    out = run_pipeline(frames, steps)
    assert out is frames
