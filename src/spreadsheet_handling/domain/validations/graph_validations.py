"""Bounded graph-shaped validation for configured node/edge networks."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from spreadsheet_handling.domain._cell_primitives import _is_empty_cell
from spreadsheet_handling.domain.validations.reference_validations import (
    ReferenceFinding,
    findings_to_frame,
)

Frames = dict[str, Any]

_VALID_MODES = {"warn", "fail", "ignore"}
_VALID_CHECKS = {"endpoints_exist", "unique_edges"}


@dataclass(frozen=True)
class NodeSpec:
    name: str
    frame: str
    key: list[str]


@dataclass(frozen=True)
class EdgeSpec:
    name: str
    frame: str
    source_node: str
    source_columns: list[str]
    target_node: str
    target_columns: list[str]
    unique: bool
    unique_columns: list[str]


def validate_graph(
    frames: Mapping[str, Any],
    *,
    graph: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    checks: Iterable[str] | None = None,
    mode: str = "warn",
    findings: str = "graph_validation_findings",
    name: str | None = None,
) -> Frames:
    """Validate configured graph endpoints and duplicate edges."""
    _valid_name(graph, "graph")
    mode = _valid_mode(mode)
    findings_frame = _valid_name(findings, "findings")
    active_checks = _valid_checks(checks)
    node_specs = _node_specs(nodes)
    edge_specs = _edge_specs(edges)
    _validate_graph_config(frames, nodes=node_specs, edges=edge_specs)

    validation_findings: list[ReferenceFinding] = []
    if "endpoints_exist" in active_checks:
        validation_findings.extend(
            _endpoint_findings(frames, graph=graph, nodes=node_specs, edges=edge_specs)
        )
    if "unique_edges" in active_checks:
        validation_findings.extend(
            _unique_edge_findings(frames, graph=graph, edges=edge_specs)
        )

    if mode == "fail" and validation_findings:
        raise ValueError(_failure_message(validation_findings, name=name or graph))

    if mode != "warn":
        return dict(frames)

    out = dict(frames)
    out[findings_frame] = findings_to_frame(validation_findings)
    return out


def _endpoint_findings(
    frames: Mapping[str, Any],
    *,
    graph: str,
    nodes: dict[str, NodeSpec],
    edges: list[EdgeSpec],
) -> list[ReferenceFinding]:
    node_keys = {
        node_name: _key_set(_require_frame(frames, spec.frame), spec.key)
        for node_name, spec in nodes.items()
    }
    findings: list[ReferenceFinding] = []
    for edge in edges:
        edge_frame = _require_frame(frames, edge.frame)
        source_node = nodes[edge.source_node]
        target_node = nodes[edge.target_node]
        for row_index, key in _row_keys(edge_frame, edge.source_columns):
            if any(_is_empty_cell(value) for value in key) or _key_token(key) not in node_keys[edge.source_node]:
                findings.append(
                    _endpoint_finding(
                        graph=graph,
                        edge=edge,
                        node=source_node,
                        columns=edge.source_columns,
                        row_index=row_index,
                        value=key,
                        endpoint_role="source",
                    )
                )
        for row_index, key in _row_keys(edge_frame, edge.target_columns):
            if any(_is_empty_cell(value) for value in key) or _key_token(key) not in node_keys[edge.target_node]:
                findings.append(
                    _endpoint_finding(
                        graph=graph,
                        edge=edge,
                        node=target_node,
                        columns=edge.target_columns,
                        row_index=row_index,
                        value=key,
                        endpoint_role="target",
                    )
                )
    return findings


def _unique_edge_findings(
    frames: Mapping[str, Any],
    *,
    graph: str,
    edges: list[EdgeSpec],
) -> list[ReferenceFinding]:
    findings: list[ReferenceFinding] = []
    for edge in edges:
        if not edge.unique:
            continue
        edge_frame = _require_frame(frames, edge.frame)
        row_keys = _row_keys(edge_frame, edge.unique_columns)
        counts = Counter(_key_token(key) for _, key in row_keys)
        for row_index, key in row_keys:
            if counts[_key_token(key)] <= 1:
                continue
            findings.append(
                ReferenceFinding(
                    rule_type="graph_unique_edge",
                    frame=edge.frame,
                    columns=edge.unique_columns,
                    row_index=row_index,
                    value=key,
                    severity="warn",
                    message=(
                        f"Graph {graph!r} edge {edge.name!r} contains a duplicate "
                        f"edge identity."
                    ),
                )
            )
    return findings


def _endpoint_finding(
    *,
    graph: str,
    edge: EdgeSpec,
    node: NodeSpec,
    columns: list[str],
    row_index: Any,
    value: tuple[Any, ...],
    endpoint_role: str,
) -> ReferenceFinding:
    return ReferenceFinding(
        rule_type="graph_endpoint",
        frame=edge.frame,
        columns=columns,
        row_index=row_index,
        value=value,
        target_frame=node.frame,
        target_columns=node.key,
        severity="warn",
        message=(
            f"Graph {graph!r} edge {edge.name!r} has unresolved {endpoint_role} "
            f"endpoint for node {node.name!r}."
        ),
    )


def _validate_graph_config(
    frames: Mapping[str, Any],
    *,
    nodes: dict[str, NodeSpec],
    edges: list[EdgeSpec],
) -> None:
    for node in nodes.values():
        frame = _require_frame(frames, node.frame)
        _ensure_columns(frame, node.key, frame_name=node.frame, field_name=f"node {node.name!r} key")
    for edge in edges:
        if edge.source_node not in nodes:
            raise KeyError(f"Edge {edge.name!r} references unknown source_node {edge.source_node!r}")
        if edge.target_node not in nodes:
            raise KeyError(f"Edge {edge.name!r} references unknown target_node {edge.target_node!r}")
        frame = _require_frame(frames, edge.frame)
        _ensure_columns(
            frame,
            edge.source_columns,
            frame_name=edge.frame,
            field_name=f"edge {edge.name!r} source_columns",
        )
        _ensure_columns(
            frame,
            edge.target_columns,
            frame_name=edge.frame,
            field_name=f"edge {edge.name!r} target_columns",
        )
        _ensure_columns(
            frame,
            edge.unique_columns,
            frame_name=edge.frame,
            field_name=f"edge {edge.name!r} unique_columns",
        )
        source_key = nodes[edge.source_node].key
        target_key = nodes[edge.target_node].key
        if len(edge.source_columns) != len(source_key):
            raise ValueError(
                f"Edge {edge.name!r} source_columns {edge.source_columns!r} must match "
                f"source node key arity {source_key!r}"
            )
        if len(edge.target_columns) != len(target_key):
            raise ValueError(
                f"Edge {edge.name!r} target_columns {edge.target_columns!r} must match "
                f"target node key arity {target_key!r}"
            )


def _node_specs(raw_nodes: list[dict[str, Any]]) -> dict[str, NodeSpec]:
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("validate_graph nodes must be a non-empty list")
    specs: dict[str, NodeSpec] = {}
    for index, raw in enumerate(raw_nodes, start=1):
        if not isinstance(raw, Mapping):
            raise TypeError(f"validate_graph node #{index} must be a mapping")
        spec = NodeSpec(
            name=_mapping_string(raw, "name", context=f"node #{index}"),
            frame=_mapping_string(raw, "frame", context=f"node {raw.get('name', index)!r}"),
            key=_key_columns(raw, singular="key", plural="keys", context=f"node {raw.get('name', index)!r}"),
        )
        if spec.name in specs:
            raise ValueError(f"Duplicate graph node name {spec.name!r}")
        specs[spec.name] = spec
    return specs


def _edge_specs(raw_edges: list[dict[str, Any]]) -> list[EdgeSpec]:
    if not isinstance(raw_edges, list) or not raw_edges:
        raise ValueError("validate_graph edges must be a non-empty list")
    specs: list[EdgeSpec] = []
    names: set[str] = set()
    for index, raw in enumerate(raw_edges, start=1):
        if not isinstance(raw, Mapping):
            raise TypeError(f"validate_graph edge #{index} must be a mapping")
        name = _mapping_string(raw, "name", context=f"edge #{index}")
        if name in names:
            raise ValueError(f"Duplicate graph edge name {name!r}")
        source_columns = _key_columns(
            raw,
            singular="source_column",
            plural="source_columns",
            context=f"edge {name!r}",
        )
        target_columns = _key_columns(
            raw,
            singular="target_column",
            plural="target_columns",
            context=f"edge {name!r}",
        )
        unique_columns = (
            _string_list(raw["unique_columns"], f"edge {name!r}.unique_columns")
            if raw.get("unique_columns") is not None
            else list(dict.fromkeys([*source_columns, *target_columns]))
        )
        specs.append(
            EdgeSpec(
                name=name,
                frame=_mapping_string(raw, "frame", context=f"edge {name!r}"),
                source_node=_mapping_string(raw, "source_node", context=f"edge {name!r}"),
                source_columns=source_columns,
                target_node=_mapping_string(raw, "target_node", context=f"edge {name!r}"),
                target_columns=target_columns,
                unique=bool(raw.get("unique", False)),
                unique_columns=unique_columns,
            )
        )
        names.add(name)
    return specs


def _key_columns(
    mapping: Mapping[str, Any],
    *,
    singular: str,
    plural: str,
    context: str,
) -> list[str]:
    configured = [name for name in (singular, plural) if mapping.get(name) is not None]
    if len(configured) != 1:
        raise ValueError(f"{context} must configure exactly one of {singular!r} or {plural!r}")
    return _string_list(mapping[configured[0]], f"{context}.{configured[0]}")


def _valid_checks(checks: Iterable[str] | None) -> set[str]:
    if checks is None:
        return set(_VALID_CHECKS)
    result = set(_string_list(checks, "checks"))
    unknown = sorted(result - _VALID_CHECKS)
    if unknown:
        raise ValueError(f"Unsupported graph validation check(s): {unknown!r}")
    if not result:
        raise ValueError("validate_graph checks must not be empty")
    return result


def _valid_mode(mode: str) -> str:
    if mode not in _VALID_MODES:
        raise ValueError(f"validate_graph mode must be one of {sorted(_VALID_MODES)!r}")
    return mode


def _valid_name(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"validate_graph {field_name} must be a non-empty string")
    return value


def _mapping_string(mapping: Mapping[str, Any], field_name: str, *, context: str) -> str:
    value = mapping.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"validate_graph {context}.{field_name} must be a non-empty string")
    return value


def _string_list(value: Any, field_name: str) -> list[str]:
    if isinstance(value, str):
        result = [value]
    elif isinstance(value, Iterable):
        result = list(value)
    else:
        raise ValueError(f"validate_graph {field_name} must be a string or list")
    if not result:
        raise ValueError(f"validate_graph {field_name} must not be empty")
    invalid = [item for item in result if not isinstance(item, str) or not item.strip()]
    if invalid:
        raise ValueError(f"validate_graph {field_name} must contain non-empty strings: {invalid!r}")
    duplicates = [item for item in dict.fromkeys(item for item in result if result.count(item) > 1)]
    if duplicates:
        raise ValueError(f"validate_graph {field_name} must not contain duplicates: {duplicates!r}")
    return result


def _require_frame(frames: Mapping[str, Any], name: str) -> pd.DataFrame:
    frame = frames.get(name)
    if not isinstance(frame, pd.DataFrame):
        raise KeyError(f"validate_graph expected DataFrame frame {name!r}")
    if isinstance(frame.columns, pd.MultiIndex) or any(isinstance(column, tuple) for column in frame.columns):
        raise ValueError(f"Frame {name!r} must have flat columns")
    if len(set(frame.columns)) != len(frame.columns):
        raise ValueError(f"Frame {name!r} must not contain duplicate columns")
    return frame


def _ensure_columns(
    frame: pd.DataFrame,
    columns: list[str],
    *,
    frame_name: str,
    field_name: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise KeyError(
            f"Frame {frame_name!r} is missing configured {field_name} column(s): {missing!r}"
        )


def _key_set(frame: pd.DataFrame, columns: list[str]) -> set[tuple[str, ...]]:
    return {
        _key_token(key)
        for _, key in _row_keys(frame, columns)
        if not any(_is_empty_cell(value) for value in key)
    }


def _row_keys(frame: pd.DataFrame, columns: list[str]) -> list[tuple[Any, tuple[Any, ...]]]:
    return [
        (row_index, tuple(_plain_value(row[column]) for column in columns))
        for row_index, row in frame.loc[:, columns].iterrows()
    ]


def _plain_value(value: Any) -> Any:
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (AttributeError, TypeError, ValueError):
            pass
    if _is_empty_cell(value):
        return None
    return value


def _key_token(key: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple("" if value is None else str(value) for value in key)


def _failure_message(findings: list[ReferenceFinding], *, name: str) -> str:
    lines = [_finding_line(finding) for finding in findings[:10]]
    suffix = "" if len(findings) <= 10 else f"\n  ... {len(findings) - 10} more finding(s)"
    return (
        f"validate_graph {name!r} failed with {len(findings)} finding(s):\n"
        + "\n".join(f"  - {line}" for line in lines)
        + suffix
    )


def _finding_line(finding: ReferenceFinding) -> str:
    record = finding.to_record()
    row = f" row {record['row_index']}" if record["row_index"] != "" else ""
    value = f" value={record['value']!r}" if record["value"] != "" else ""
    target = (
        f" -> {record['target_frame']}({record['target_columns']})"
        if record["target_frame"]
        else ""
    )
    return (
        f"{record['rule_type']} {record['frame']}({record['columns']})"
        f"{target}{row}{value}: {record['message']}"
    )
