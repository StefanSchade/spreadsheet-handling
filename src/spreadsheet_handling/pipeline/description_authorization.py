"""Less-trusted pipeline-description authorization.

The trusted operator constructs the public value in this module outside the
description.  It authorizes exact registered names and exact canonical plugin
targets; authorized plugins remain trusted same-process Python under their
complete current argument contract.  This is deliberately not a sandbox or a
general filesystem/security policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .dotted_paths import canonicalize_configuration_callable
from .registry import REGISTRY


_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_POLICY_MAPPING_TYPES = (dict, _MAPPING_PROXY_TYPE)
_POLICY_COLLECTION_TYPES = (list, tuple, set, frozenset)
_SAFE_DESCRIPTION_SCALAR_TYPES = (str, bytes, int, float, bool, type(None))
_RESERVED_DESCRIPTION_KEYS = frozenset(
    {
        "description_authority",
        "description_authorization",
        "description_policy",
    }
)

_ORDINARY_REGISTERED_STEPS = (
    "identity",
    "validate",
    "add_fk_helpers",
    "remove_fk_helpers",
    "validate_fk_helpers",
    "flatten_headers",
    "unflatten_headers",
    "reorder_fk_helpers",
    "add_validations",
    "validate_references",
    "validate_graph",
    "configure_workbook_view",
    "configure_pipeline_cleanup",
    "apply_workbook_view_sheet_mappings",
    "configure_lookup_helpers",
    "configure_fk_helpers",
    "infer_fk_relations",
    "bootstrap_meta",
    "split_by_discriminator",
    "merge_by_discriminator",
    "extract_frame",
    "pivot_frame",
    "join_frames",
    "expand_xref",
    "contract_xref",
    "project_axis_labels",
    "restore_axis_keys",
    "contract_grouped_xref",
    "expand_grouped_xref",
    "reconstruct_grouped_matrix",
    "sparse_collapse",
    "sparse_expand",
    "normalize_resource_overrides",
    "decode_cell_values",
    "encode_cell_values",
    "expand_compact_multiaxis",
    "contract_compact_multiaxis",
    "add_lookup_helpers",
    "apply_derived_column_policy",
)

# This package-complete table is intentionally independent of REGISTRY
# membership.  A new registration remains unavailable in less-trusted mode
# until it is deliberately classified here and the completeness guard updated.
_REGISTERED_STEP_CLASSIFICATIONS = MappingProxyType(
    {
        **{name: "ordinary" for name in _ORDINARY_REGISTERED_STEPS},
        "apply_overrides": "inline-overrides-only",
        "write_structured_yaml": "root-contained-writer",
        "write_key_value_resources": "root-contained-writer",
        "write_artifact_manifest": "artifact-manifest",
    }
)


class DescriptionAuthorizationError(ValueError):
    """A safe, focused less-trusted-description rejection."""

    def __init__(
        self,
        kind: str,
        reason: str,
        *,
        step_index: int | None = None,
        identifier: str | None = None,
        field: str | None = None,
    ) -> None:
        self.kind = kind
        self.reason = reason
        self.step_index = step_index
        self.identifier = identifier
        self.field = field
        parts = [f"description authorization failed: {kind}", f"reason={reason}"]
        if step_index is not None:
            parts.append(f"step={step_index}")
        if identifier is not None:
            parts.append(f"identifier={identifier}")
        if field is not None:
            parts.append(f"field={field}")
        super().__init__("; ".join(parts))


@dataclass(frozen=True, slots=True)
class _StepAuthority:
    output_roots: frozenset[Path] = frozenset()
    allow_checksum_reads: bool = False


@dataclass(frozen=True, slots=True, init=False, repr=False)
class LessTrustedDescriptionAuthorization:
    """Immutable operator authority for less-trusted step descriptions.

    Construct with :meth:`from_mapping`.  Exact plugin authorization accepts
    the selected plugin under its complete current argument contract; plugin
    arguments are not interpreted as a generic policy language.
    """

    _registered_steps: MappingProxyType
    _plugin_targets: frozenset[str]

    @classmethod
    def from_mapping(cls, value: Any) -> LessTrustedDescriptionAuthorization:
        if type(value) not in _POLICY_MAPPING_TYPES:
            _invalid_policy("top_level_not_mapping")
        unknown = [
            key
            for key in value
            if type(key) is not str
            or key not in {"registered_steps", "plugin_targets"}
        ]
        if unknown:
            _invalid_policy("unknown_top_level_field")

        raw_registered = value.get("registered_steps", {})
        if type(raw_registered) not in _POLICY_MAPPING_TYPES:
            _invalid_policy("registered_steps_not_mapping")

        registered: dict[str, _StepAuthority] = {}
        for name, constraints in raw_registered.items():
            if type(name) is not str:
                _invalid_policy("registered_step_name_not_exact_string")
            if name == "plugin":
                _invalid_policy("plugin_not_registered_step")
            if name not in REGISTRY:
                _invalid_policy("unknown_registered_step")
            classification = _REGISTERED_STEP_CLASSIFICATIONS.get(name)
            if classification is None:
                _invalid_policy("unclassified_registered_step")
            registered[name] = _parse_step_authority(name, classification, constraints)

        raw_targets = value.get("plugin_targets", ())
        if type(raw_targets) not in _POLICY_COLLECTION_TYPES:
            _invalid_policy("plugin_targets_not_collection")
        canonical_targets: set[str] = set()
        for target in raw_targets:
            if type(target) is not str:
                _invalid_policy("plugin_target_not_exact_string")
            try:
                canonical = canonicalize_configuration_callable(target)
            except (TypeError, ValueError):
                _invalid_policy("malformed_or_blocked_plugin_target")
            if canonical in canonical_targets:
                _invalid_policy("duplicate_canonical_plugin_target")
            canonical_targets.add(canonical)

        instance = object.__new__(cls)
        object.__setattr__(instance, "_registered_steps", MappingProxyType(dict(registered)))
        object.__setattr__(instance, "_plugin_targets", frozenset(canonical_targets))
        return instance


@dataclass(frozen=True, slots=True)
class _EffectiveAuthorization:
    registered_steps: MappingProxyType
    plugin_targets: frozenset[str]


def _effective_authorization(value: Any) -> _EffectiveAuthorization:
    if type(value) is not LessTrustedDescriptionAuthorization:
        _invalid_policy("unsupported_authorization_value")
    return _EffectiveAuthorization(
        registered_steps=MappingProxyType(dict(value._registered_steps)),
        plugin_targets=frozenset(value._plugin_targets),
    )


def _parse_step_authority(name: str, classification: str, raw: Any) -> _StepAuthority:
    if type(raw) not in _POLICY_MAPPING_TYPES:
        _invalid_policy("step_constraints_not_mapping")
    fields = set(raw)
    if classification in {"ordinary", "inline-overrides-only"}:
        if fields:
            _invalid_policy("constraints_not_supported_for_step")
        return _StepAuthority()

    allowed = {"output_roots"}
    if classification == "artifact-manifest":
        allowed.add("allow_checksum_reads")
    if fields - allowed:
        _invalid_policy("unknown_or_wrong_step_constraint")

    has_roots = "output_roots" in raw
    if not has_roots:
        if classification == "root-contained-writer":
            _invalid_policy("required_output_roots_missing")
        if "allow_checksum_reads" in raw:
            _invalid_policy("checksum_permission_without_roots")
        return _StepAuthority()

    raw_roots = raw["output_roots"]
    if type(raw_roots) not in _POLICY_COLLECTION_TYPES or not raw_roots:
        _invalid_policy("output_roots_not_nonempty_collection")
    roots: set[Path] = set()
    for root in raw_roots:
        if type(root) is not str:
            _invalid_policy("output_root_not_exact_string")
        try:
            path = Path(root).expanduser()
        except (OSError, RuntimeError, ValueError):
            _invalid_policy("invalid_output_root")
        if not path.is_absolute():
            _invalid_policy("output_root_not_absolute")
        try:
            canonical = path.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            _invalid_policy("invalid_output_root")
        if canonical in roots:
            _invalid_policy("duplicate_canonical_output_root")
        roots.add(canonical)

    allow_reads = raw.get("allow_checksum_reads", False)
    if type(allow_reads) is not bool:
        _invalid_policy("checksum_permission_not_boolean")
    return _StepAuthority(frozenset(roots), allow_reads)


def _invalid_policy(reason: str) -> None:
    raise DescriptionAuthorizationError("invalid_policy", reason)


def _snapshot_less_trusted_step_specs(step_specs: Any) -> list[dict[str, Any]]:
    if type(step_specs) not in (list, tuple):
        raise DescriptionAuthorizationError(
            "malformed_description", "step_collection_not_builtin_sequence"
        )
    snapshots: list[dict[str, Any]] = []
    try:
        for index, raw in enumerate(step_specs, start=1):
            if type(raw) is not dict:
                raise DescriptionAuthorizationError(
                    "malformed_description",
                    "step_shell_not_builtin_dict",
                    step_index=index,
                )
            snapshot = _snapshot_builtin(raw, active=set())
            snapshots.append(snapshot)
    except RecursionError as exc:
        raise DescriptionAuthorizationError(
            "malformed_description", "description_nesting_too_deep"
        ) from exc
    return snapshots


def _snapshot_builtin(value: Any, *, active: set[int]) -> Any:
    if type(value) in _SAFE_DESCRIPTION_SCALAR_TYPES:
        return value
    value_type = type(value)
    if value_type not in (dict, list, tuple, set, frozenset):
        raise DescriptionAuthorizationError(
            "malformed_description", "unsupported_description_value_type"
        )

    identity = id(value)
    if identity in active:
        raise DescriptionAuthorizationError("malformed_description", "cyclic_description")
    active.add(identity)
    try:
        if value_type is dict:
            result: dict[Any, Any] = {}
            for key, item in value.items():
                copied_key = _snapshot_builtin(key, active=active)
                copied_item = _snapshot_builtin(item, active=active)
                try:
                    result[copied_key] = copied_item
                except TypeError as exc:
                    raise DescriptionAuthorizationError(
                        "malformed_description", "unsupported_description_mapping_key"
                    ) from exc
            return result
        copied = [_snapshot_builtin(item, active=active) for item in value]
        if value_type is list:
            return copied
        if value_type is tuple:
            return tuple(copied)
        try:
            return set(copied) if value_type is set else frozenset(copied)
        except TypeError as exc:
            raise DescriptionAuthorizationError(
                "malformed_description", "unsupported_description_set_member"
            ) from exc
    finally:
        active.remove(identity)


def _authorize_step_spec(
    spec: dict[str, Any],
    *,
    step_index: int,
    authorization: _EffectiveAuthorization,
    cwd: Path,
) -> dict[str, Any]:
    if any(type(key) is not str for key in spec):
        raise DescriptionAuthorizationError(
            "malformed_description", "step_parameter_key_not_exact_string", step_index=step_index
        )

    step_id = spec.get("step")
    if type(step_id) is not str or not step_id:
        raise DescriptionAuthorizationError(
            "malformed_description", "step_identifier_not_nonempty_exact_string", step_index=step_index
        )

    reserved = _RESERVED_DESCRIPTION_KEYS.intersection(spec)
    if reserved:
        raise DescriptionAuthorizationError(
            "invalid_policy_request",
            "reserved_description_policy_key",
            step_index=step_index,
            identifier=step_id,
        )

    if step_id == "plugin":
        _authorize_plugin(spec, step_index=step_index, authorization=authorization)
        return spec

    if step_id not in REGISTRY:
        kind = "forbidden_capability" if ":" in step_id else "unknown_capability"
        reason = "direct_colon_factory_forbidden" if ":" in step_id else "unknown_step"
        raise DescriptionAuthorizationError(
            kind, reason, step_index=step_index, identifier=step_id
        )

    classification = _REGISTERED_STEP_CLASSIFICATIONS.get(step_id)
    if classification is None:
        raise DescriptionAuthorizationError(
            "forbidden_capability",
            "registered_step_unclassified",
            step_index=step_index,
            identifier=step_id,
        )

    step_authority = authorization.registered_steps.get(step_id)
    if step_authority is None:
        raise DescriptionAuthorizationError(
            "forbidden_identifier",
            "registered_step_not_authorized",
            step_index=step_index,
            identifier=step_id,
        )

    if classification == "inline-overrides-only":
        _authorize_apply_overrides(spec, step_index=step_index, identifier=step_id)
    elif classification == "root-contained-writer":
        root = _authorize_output_root(
            spec,
            step_authority,
            step_index=step_index,
            identifier=step_id,
            cwd=cwd,
        )
        if step_id == "write_structured_yaml":
            _authorize_structured_yaml(spec, root, step_index=step_index, identifier=step_id)
        else:
            _authorize_key_value_writer(spec, step_index=step_index, identifier=step_id)
    elif classification == "artifact-manifest":
        _authorize_artifact_manifest(
            spec,
            step_authority,
            step_index=step_index,
            identifier=step_id,
            cwd=cwd,
        )
    return spec


def _authorize_plugin(
    spec: dict[str, Any],
    *,
    step_index: int,
    authorization: _EffectiveAuthorization,
) -> None:
    dotted = spec.get("dotted")
    if type(dotted) is not str:
        raise DescriptionAuthorizationError(
            "malformed_description",
            "plugin_target_not_exact_string",
            step_index=step_index,
            identifier="plugin",
            field="dotted",
        )
    try:
        canonical = canonicalize_configuration_callable(dotted)
    except (TypeError, ValueError) as exc:
        raise DescriptionAuthorizationError(
            "malformed_description",
            "malformed_or_blocked_plugin_target",
            step_index=step_index,
            identifier="plugin",
            field="dotted",
        ) from exc
    if canonical not in authorization.plugin_targets:
        raise DescriptionAuthorizationError(
            "forbidden_identifier",
            "plugin_target_not_authorized",
            step_index=step_index,
            identifier=canonical,
            field="dotted",
        )


def _authorize_apply_overrides(
    spec: dict[str, Any], *, step_index: int, identifier: str
) -> None:
    if "overrides_path" in spec and spec["overrides_path"] is not None:
        raise DescriptionAuthorizationError(
            "forbidden_resource_selector",
            "external_overrides_path_forbidden",
            step_index=step_index,
            identifier=identifier,
            field="overrides_path",
        )


def _canonical_description_path(value: str, cwd: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return candidate.resolve(strict=False)


def _authorize_output_root(
    spec: dict[str, Any],
    authority: _StepAuthority,
    *,
    step_index: int,
    identifier: str,
    cwd: Path,
) -> Path:
    output_dir = spec.get("output_dir")
    if type(output_dir) is not str:
        raise DescriptionAuthorizationError(
            "malformed_description",
            "output_dir_not_exact_string",
            step_index=step_index,
            identifier=identifier,
            field="output_dir",
        )
    try:
        canonical = _canonical_description_path(output_dir, cwd)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DescriptionAuthorizationError(
            "malformed_description",
            "invalid_output_dir",
            step_index=step_index,
            identifier=identifier,
            field="output_dir",
        ) from exc
    if canonical not in authority.output_roots:
        raise DescriptionAuthorizationError(
            "forbidden_resource_selector",
            "output_root_not_authorized",
            step_index=step_index,
            identifier=identifier,
            field="output_dir",
        )
    spec["output_dir"] = str(canonical)
    return canonical


def _authorize_relative_path(
    path_label: str,
    root: Path,
    *,
    step_index: int,
    identifier: str,
    field: str,
) -> None:
    try:
        relative = Path(path_label)
        if relative.is_absolute():
            raise ValueError
        target = (root / relative).resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DescriptionAuthorizationError(
            "forbidden_resource_selector",
            "subordinate_path_not_relative_and_contained",
            step_index=step_index,
            identifier=identifier,
            field=field,
        ) from exc
    if not target.is_relative_to(root):
        raise DescriptionAuthorizationError(
            "forbidden_resource_selector",
            "subordinate_path_not_relative_and_contained",
            step_index=step_index,
            identifier=identifier,
            field=field,
        )


def _authorize_structured_yaml(
    spec: dict[str, Any], root: Path, *, step_index: int, identifier: str
) -> None:
    files = spec.get("files")
    if type(files) not in (list, tuple):
        raise DescriptionAuthorizationError(
            "malformed_description",
            "files_not_builtin_sequence",
            step_index=step_index,
            identifier=identifier,
            field="files",
        )
    for file_spec in files:
        if type(file_spec) is not dict:
            raise DescriptionAuthorizationError(
                "malformed_description",
                "file_spec_not_builtin_dict",
                step_index=step_index,
                identifier=identifier,
                field="files",
            )
        path_label = file_spec.get("path")
        if type(path_label) is not str or not path_label.strip():
            raise DescriptionAuthorizationError(
                "malformed_description",
                "file_path_not_nonempty_exact_string",
                step_index=step_index,
                identifier=identifier,
                field="files.path",
            )
        _authorize_relative_path(
            path_label,
            root,
            step_index=step_index,
            identifier=identifier,
            field="files.path",
        )


def _authorize_key_value_writer(
    spec: dict[str, Any], *, step_index: int, identifier: str
) -> None:
    if type(spec.get("file_pattern")) is not str:
        raise DescriptionAuthorizationError(
            "malformed_description",
            "file_pattern_not_exact_string",
            step_index=step_index,
            identifier=identifier,
            field="file_pattern",
        )


def _authorize_artifact_manifest(
    spec: dict[str, Any],
    authority: _StepAuthority,
    *,
    step_index: int,
    identifier: str,
    cwd: Path,
) -> None:
    output_dir = spec.get("output_dir")
    manifest_path = spec.get("manifest_path")
    checksum = spec.get("checksum")
    if output_dir is None:
        if manifest_path is not None or checksum is not None:
            raise DescriptionAuthorizationError(
                "forbidden_resource_selector",
                "manifest_io_requires_output_root",
                step_index=step_index,
                identifier=identifier,
            )
        return

    root = _authorize_output_root(
        spec,
        authority,
        step_index=step_index,
        identifier=identifier,
        cwd=cwd,
    )
    if manifest_path is not None:
        if type(manifest_path) is not str:
            raise DescriptionAuthorizationError(
                "malformed_description",
                "manifest_path_not_exact_string",
                step_index=step_index,
                identifier=identifier,
                field="manifest_path",
            )
        _authorize_relative_path(
            manifest_path,
            root,
            step_index=step_index,
            identifier=identifier,
            field="manifest_path",
        )
    if checksum is not None:
        if type(checksum) is not str or checksum != "sha256":
            raise DescriptionAuthorizationError(
                "malformed_description",
                "unsupported_checksum",
                step_index=step_index,
                identifier=identifier,
                field="checksum",
            )
        if not authority.allow_checksum_reads:
            raise DescriptionAuthorizationError(
                "forbidden_resource_selector",
                "checksum_reads_not_authorized",
                step_index=step_index,
                identifier=identifier,
                field="checksum",
            )


__all__ = ["DescriptionAuthorizationError", "LessTrustedDescriptionAuthorization"]
