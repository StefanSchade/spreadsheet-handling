"""Structured YAML writer for generated configuration trees."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from numbers import Number
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

Frames = dict[str, Any]


def write_structured_yaml(
    frames: Mapping[str, Any],
    *,
    output_dir: str | Path,
    files: Iterable[Mapping[str, Any]],
    report_frame: str | None = "structured_yaml_files",
) -> Frames:
    """Write configured nested YAML files from tabular frames.

    Supported file shapes:

    * ``root: mapping`` with ``key`` and ``value`` renders a mapping keyed by
      one or more key columns.
    * ``root: mapping`` with ``key`` and ``sequence`` renders a grouped
      sequence per key.
    * ``root: list`` with ``value`` renders a top-level YAML list.

    The existing flat YAML backend remains separate; this writer is a pipeline
    projection step for explicit configuration trees.
    """
    if isinstance(files, (str, bytes)):
        raise TypeError("files must be a list of file specs, not a string")
    file_specs = list(files)
    if not file_specs:
        raise ValueError("write_structured_yaml requires at least one file spec")
    if report_frame is not None and (not isinstance(report_frame, str) or not report_frame.strip()):
        raise TypeError("report_frame must be a non-empty string or None")

    out_dir = _safe_output_dir(output_dir)
    prepared_specs: list[tuple[dict[str, Any], str, str, str, Path]] = []
    target_paths: dict[Path, str] = {}
    for index, raw_spec in enumerate(file_specs, start=1):
        if not isinstance(raw_spec, Mapping):
            raise TypeError(f"File spec #{index} must be a mapping")
        spec = dict(raw_spec)
        path_label = _required_string(spec, "path", file_index=index)
        frame_name = _required_string(spec, "frame", file_index=index)
        root = str(spec.get("root") or "mapping")
        target_path = _safe_target_path(out_dir, path_label)
        if target_path in target_paths:
            raise ValueError(
                f"Structured YAML path {path_label!r} duplicates "
                f"previous file path {target_paths[target_path]!r}"
            )
        target_paths[target_path] = path_label
        prepared_specs.append((spec, path_label, frame_name, root, target_path))

    reports: list[dict[str, Any]] = []
    for spec, path_label, frame_name, root, target_path in prepared_specs:
        df = _require_frame(frames, frame_name)
        data = _render_file_spec(df, spec, frame_name=frame_name, path_label=path_label, root=root)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("w", encoding="utf-8", newline="\n") as handle:
            yaml.safe_dump(
                data,
                handle,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
                width=4096,
            )

        reports.append(
            {
                "path": path_label,
                "frame": frame_name,
                "root": root,
                "rows": len(df),
                "bytes": target_path.stat().st_size,
            }
        )

    out = dict(frames)
    if report_frame is not None:
        out[report_frame] = pd.DataFrame(
            reports,
            columns=["path", "frame", "root", "rows", "bytes"],
        )
    return out


def _render_file_spec(
    df: pd.DataFrame,
    spec: Mapping[str, Any],
    *,
    frame_name: str,
    path_label: str,
    root: str,
) -> Any:
    if root == "mapping":
        if "sequence" in spec:
            return _render_grouped_sequence(
                df,
                spec,
                frame_name=frame_name,
                path_label=path_label,
            )
        return _render_mapping(
            df,
            spec,
            frame_name=frame_name,
            path_label=path_label,
        )
    if root == "list":
        return _render_list(
            df,
            spec,
            frame_name=frame_name,
            path_label=path_label,
        )
    raise ValueError(
        f"File {path_label!r} has unsupported root {root!r}; expected 'mapping' or 'list'"
    )


def _render_mapping(
    df: pd.DataFrame,
    spec: Mapping[str, Any],
    *,
    frame_name: str,
    path_label: str,
) -> dict[Any, Any]:
    key_columns = _column_list(spec.get("key"), "key", frame_name=frame_name, path_label=path_label)
    value_spec = _value_spec(spec, frame_name=frame_name, path_label=path_label)
    omit_empty = _path_set(spec.get("omit_empty"), field_name="omit_empty", path_label=path_label)
    sort_by = _sort_columns(spec.get("sort_by"), frame_name=frame_name, path_label=path_label)
    _ensure_columns(df, [*key_columns, *sort_by, *value_spec.values()], frame_name=frame_name)

    data: dict[Any, Any] = {}
    for row_index, row in _ordered_rows(df, sort_by or key_columns):
        key = _key_tuple(
            row, key_columns, frame_name=frame_name, path_label=path_label, row_index=row_index
        )
        value = _render_value(
            row,
            value_spec,
            omit_empty=omit_empty,
            frame_name=frame_name,
            path_label=path_label,
            row_index=row_index,
        )
        _assign_nested_key(data, key, value, path_label=path_label)
    return data


def _render_grouped_sequence(
    df: pd.DataFrame,
    spec: Mapping[str, Any],
    *,
    frame_name: str,
    path_label: str,
) -> dict[Any, Any]:
    key_columns = _column_list(spec.get("key"), "key", frame_name=frame_name, path_label=path_label)
    sequence = spec.get("sequence")
    if not isinstance(sequence, Mapping):
        raise ValueError(f"File {path_label!r} sequence must be a mapping")
    sequence_spec = dict(sequence)
    value_spec = _value_spec(sequence_spec, frame_name=frame_name, path_label=path_label)
    omit_empty = _path_set(
        sequence_spec.get("omit_empty", spec.get("omit_empty")),
        field_name="omit_empty",
        path_label=path_label,
    )
    sort_by = _sort_columns(
        sequence_spec.get("sort_by"), frame_name=frame_name, path_label=path_label
    )
    _ensure_columns(df, [*key_columns, *sort_by, *value_spec.values()], frame_name=frame_name)

    grouped: dict[tuple[Any, ...], list[tuple[int, Mapping[str, Any]]]] = {}
    for row_index, row in _ordered_rows(df, key_columns):
        key = _key_tuple(
            row, key_columns, frame_name=frame_name, path_label=path_label, row_index=row_index
        )
        grouped.setdefault(key, []).append((row_index, row))

    data: dict[Any, Any] = {}
    for key in sorted(grouped, key=_sort_tuple):
        rows = _sort_records(grouped[key], sort_by)
        items = [
            _render_value(
                row,
                value_spec,
                omit_empty=omit_empty,
                frame_name=frame_name,
                path_label=path_label,
                row_index=row_index,
            )
            for row_index, row in rows
        ]
        _assign_nested_key(data, key, items, path_label=path_label)
    return data


def _render_list(
    df: pd.DataFrame,
    spec: Mapping[str, Any],
    *,
    frame_name: str,
    path_label: str,
) -> list[dict[str, Any]]:
    value_spec = _value_spec(spec, frame_name=frame_name, path_label=path_label)
    omit_empty = _path_set(spec.get("omit_empty"), field_name="omit_empty", path_label=path_label)
    sort_by = _sort_columns(spec.get("sort_by"), frame_name=frame_name, path_label=path_label)
    _ensure_columns(df, [*sort_by, *value_spec.values()], frame_name=frame_name)

    return [
        _render_value(
            row,
            value_spec,
            omit_empty=omit_empty,
            frame_name=frame_name,
            path_label=path_label,
            row_index=row_index,
        )
        for row_index, row in _ordered_rows(df, sort_by)
    ]


def _render_value(
    row: Mapping[str, Any],
    value_spec: Mapping[str, str],
    *,
    omit_empty: set[str],
    frame_name: str,
    path_label: str,
    row_index: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for output_path, column in value_spec.items():
        raw_value = row[column]
        if _is_empty_cell(raw_value):
            if output_path in omit_empty:
                continue
            raise ValueError(
                f"File {path_label!r}, frame {frame_name!r}, row {row_index}: "
                f"required field {output_path!r} from column {column!r} is empty"
            )
        _assign_path(out, output_path, _yaml_value(raw_value), path_label=path_label)
    return out


def _value_spec(
    spec: Mapping[str, Any],
    *,
    frame_name: str,
    path_label: str,
) -> dict[str, str]:
    raw = spec.get("value")
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError(
            f"File {path_label!r}, frame {frame_name!r}: value must be a non-empty mapping"
        )
    result: dict[str, str] = {}
    for output_path, column in raw.items():
        if not isinstance(output_path, str) or not output_path.strip():
            raise ValueError(f"File {path_label!r}: value output paths must be non-empty strings")
        _path_parts(output_path, path_label=path_label)
        if not isinstance(column, str) or not column.strip():
            raise ValueError(
                f"File {path_label!r}: value path {output_path!r} must map to a column name string"
            )
        result[output_path] = column
    return result


def _required_string(spec: Mapping[str, Any], field_name: str, *, file_index: int) -> str:
    value = spec.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"File spec #{file_index} requires non-empty string field {field_name!r}")
    return value


def _require_frame(frames: Mapping[str, Any], name: str) -> pd.DataFrame:
    if name not in frames:
        raise KeyError(f"Frame {name!r} not found")
    frame = frames[name]
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"Frame {name!r} must be a pandas DataFrame")
    if isinstance(frame.columns, pd.MultiIndex) or any(
        isinstance(col, tuple) for col in frame.columns
    ):
        raise ValueError(f"Frame {name!r} must have flat string-like columns")
    return frame


def _column_list(value: Any, field_name: str, *, frame_name: str, path_label: str) -> list[str]:
    if isinstance(value, str):
        columns = [value]
    elif isinstance(value, Iterable) and value is not None and not isinstance(value, Mapping):
        columns = list(value)
    else:
        raise ValueError(f"File {path_label!r}, frame {frame_name!r}: {field_name} is required")
    if not columns or any(not isinstance(column, str) or not column.strip() for column in columns):
        raise ValueError(
            f"File {path_label!r}, frame {frame_name!r}: {field_name} must contain column name strings"
        )
    return columns


def _sort_columns(value: Any, *, frame_name: str, path_label: str) -> list[str]:
    if value is None:
        return []
    return _column_list(value, "sort_by", frame_name=frame_name, path_label=path_label)


def _path_set(value: Any, *, field_name: str, path_label: str) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Iterable) and not isinstance(value, Mapping):
        values = list(value)
    else:
        raise ValueError(f"File {path_label!r}: {field_name} must be a string or list of strings")
    result: set[str] = set()
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"File {path_label!r}: {field_name} entries must be non-empty strings")
        _path_parts(item, path_label=path_label)
        result.add(item)
    return result


def _ensure_columns(df: pd.DataFrame, columns: Iterable[str], *, frame_name: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"Frame {frame_name!r} is missing columns: {missing!r}")


def _ordered_rows(df: pd.DataFrame, sort_by: list[str]) -> list[tuple[int, Mapping[str, Any]]]:
    records = [(index + 1, record) for index, record in enumerate(df.to_dict(orient="records"))]
    return _sort_records(records, sort_by)


def _sort_records(
    records: list[tuple[int, Mapping[str, Any]]],
    sort_by: list[str],
) -> list[tuple[int, Mapping[str, Any]]]:
    if not sort_by:
        return records
    return sorted(
        records,
        key=lambda item: (
            tuple(_sort_token(item[1][column]) for column in sort_by),
            item[0],
        ),
    )


def _key_tuple(
    row: Mapping[str, Any],
    key_columns: list[str],
    *,
    frame_name: str,
    path_label: str,
    row_index: int,
) -> tuple[Any, ...]:
    values: list[Any] = []
    for column in key_columns:
        raw_value = row[column]
        if _is_empty_cell(raw_value):
            raise ValueError(
                f"File {path_label!r}, frame {frame_name!r}, row {row_index}: "
                f"key column {column!r} is empty"
            )
        value = _yaml_value(raw_value)
        if isinstance(value, (dict, list, set, tuple)):
            raise ValueError(
                f"File {path_label!r}, frame {frame_name!r}, row {row_index}: "
                f"key column {column!r} must be scalar"
            )
        values.append(value)
    return tuple(values)


def _assign_nested_key(
    target: dict[Any, Any],
    key: tuple[Any, ...],
    value: Any,
    *,
    path_label: str,
) -> None:
    current = target
    for part in key[:-1]:
        existing = current.setdefault(part, {})
        if not isinstance(existing, dict):
            raise ValueError(f"File {path_label!r} has colliding mapping key path {key!r}")
        current = existing
    leaf = key[-1]
    if leaf in current:
        raise ValueError(f"File {path_label!r} has duplicate mapping key {key!r}")
    current[leaf] = value


def _assign_path(target: dict[str, Any], dotted_path: str, value: Any, *, path_label: str) -> None:
    parts = _path_parts(dotted_path, path_label=path_label)
    current = target
    for part in parts[:-1]:
        existing = current.setdefault(part, {})
        if not isinstance(existing, dict):
            raise ValueError(f"File {path_label!r} has colliding output path {dotted_path!r}")
        current = existing
    leaf = parts[-1]
    if leaf in current:
        raise ValueError(f"File {path_label!r} has duplicate output path {dotted_path!r}")
    current[leaf] = value


def _path_parts(dotted_path: str, *, path_label: str) -> list[str]:
    parts = dotted_path.split(".")
    if any(not part for part in parts):
        raise ValueError(f"File {path_label!r} has invalid dotted output path {dotted_path!r}")
    return parts


def _safe_output_dir(output_dir: str | Path) -> Path:
    return Path(output_dir).expanduser().resolve(strict=False)


def _safe_target_path(output_dir: Path, path_label: str) -> Path:
    rel_path = Path(path_label)
    if rel_path.is_absolute():
        raise ValueError(f"Structured YAML path {path_label!r} must be relative")
    target = (output_dir / rel_path).resolve(strict=False)
    if not target.is_relative_to(output_dir):
        raise ValueError(
            f"Structured YAML path {path_label!r} escapes output_dir {str(output_dir)!r}"
        )
    return target


def _yaml_value(value: Any) -> Any:
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (AttributeError, ValueError, TypeError):
            pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _sort_token(value: Any) -> tuple[int, Any]:
    if _is_empty_cell(value):
        return (0, "")
    converted = _yaml_value(value)
    if isinstance(converted, Number) and not isinstance(converted, bool):
        return (1, float(converted))
    return (2, str(converted))


def _sort_tuple(values: tuple[Any, ...]) -> tuple[tuple[int, Any], ...]:
    return tuple(_sort_token(value) for value in values)


def _is_empty_cell(cell_value: Any) -> bool:
    if cell_value is None:
        return True
    if isinstance(cell_value, str):
        return cell_value == ""
    try:
        return bool(pd.isna(cell_value))
    except (TypeError, ValueError):
        return False
