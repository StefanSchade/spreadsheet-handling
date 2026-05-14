"""Deterministic key-value resource file writer for long-form tuple frames.

Writes one or more .properties-style files from a configured source frame,
partitioned by template column values.  Owns serialization only — no
override/fallback semantics.
"""
from __future__ import annotations

import string
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

Frames = dict[str, Any]

_VALID_ESCAPING = {"unicode", "utf-8"}


def write_key_value_resources(
    frames: Mapping[str, Any],
    *,
    source: str,
    output_dir: str | Path,
    file_pattern: str,
    key: str,
    value: str,
    sort_by: list[str] | str | None = None,
    encoding: str = "utf-8",
    properties_escaping: str = "unicode",
    report_frame: str | None = "key_value_resource_files",
    name: str | None = None,
) -> Frames:
    """Write deterministic key-value files from a configured source frame.

    ``file_pattern`` accepts ``{column_name}`` placeholders; the source frame is
    grouped by those columns and one file is written per group.  No placeholders
    → a single file from the whole frame.

    ``properties_escaping`` values:

    * ``"unicode"`` — non-ASCII chars encoded as ``\\uXXXX`` (Java
      ``Properties.load()`` ISO-8859-1 compatible).
    * ``"utf-8"`` — raw UTF-8; only ``\\``, newlines, and tabs are escaped.

    The report frame uses provisional columns ``path``, ``frame``, ``rows``,
    ``bytes`` — consistent with ``write_structured_yaml``.
    ``FTR-GENERATED-ARTIFACT-MANIFEST-P4A`` will define the final shared shape;
    column alignment is deferred to that FTR.
    """
    del name
    if properties_escaping not in _VALID_ESCAPING:
        raise ValueError(
            f"Unsupported properties_escaping {properties_escaping!r}; "
            f"expected one of {sorted(_VALID_ESCAPING)!r}"
        )
    if report_frame is not None and (
        not isinstance(report_frame, str) or not report_frame.strip()
    ):
        raise TypeError("report_frame must be a non-empty string or None")

    out_dir = _safe_output_dir(output_dir)
    df = _require_frame(frames, source)
    partition_cols = _partition_columns(file_pattern)
    sort_cols = _as_list(sort_by)
    required_cols = [key, value, *partition_cols, *sort_cols]
    _ensure_columns(df, required_cols, frame_name=source)

    if sort_cols:
        df = df.sort_values(sort_cols, kind="stable")

    groups = _partition_groups(df, partition_cols)
    target_paths: dict[Path, str] = {}
    reports: list[dict[str, Any]] = []

    for group_values, group_df in groups:
        path_label = _render_pattern(file_pattern, partition_cols, group_values)
        target_path = _safe_target_path(out_dir, path_label)
        if target_path in target_paths:
            raise ValueError(
                f"Key-value path {path_label!r} duplicates previous path "
                f"{target_paths[target_path]!r}"
            )
        target_paths[target_path] = path_label

        _check_duplicate_keys(group_df, key_col=key, path_label=path_label)

        content = _render_properties_content(group_df, key_col=key, value_col=value, escaping=properties_escaping)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("w", encoding=encoding, newline="\n") as fh:
            fh.write(content)

        reports.append({
            "path": path_label,
            "frame": source,
            "rows": len(group_df),
            "bytes": target_path.stat().st_size,
        })

    out = dict(frames)
    if report_frame is not None:
        out[report_frame] = pd.DataFrame(reports, columns=["path", "frame", "rows", "bytes"])
    return out


def _partition_columns(file_pattern: str) -> list[str]:
    cols: list[str] = []
    for _, field_name, _, _ in string.Formatter().parse(file_pattern):
        if field_name is not None and field_name:
            cols.append(field_name)
    return cols


def _render_pattern(
    file_pattern: str,
    partition_cols: list[str],
    group_values: tuple[Any, ...],
) -> str:
    mapping = dict(zip(partition_cols, group_values))
    return file_pattern.format(**mapping)


def _partition_groups(
    df: pd.DataFrame,
    partition_cols: list[str],
) -> list[tuple[tuple[Any, ...], pd.DataFrame]]:
    if not partition_cols:
        return [((), df)]
    groups: list[tuple[tuple[Any, ...], pd.DataFrame]] = []
    for key_vals, group_df in df.groupby(partition_cols, sort=True, dropna=False):
        if isinstance(key_vals, tuple):
            groups.append((key_vals, group_df))
        else:
            groups.append(((key_vals,), group_df))
    return groups


def _check_duplicate_keys(df: pd.DataFrame, *, key_col: str, path_label: str) -> None:
    duplicated = df[key_col][df[key_col].duplicated()]
    if not duplicated.empty:
        first_dup = str(duplicated.iloc[0])
        raise ValueError(
            f"Key-value file {path_label!r}: duplicate key {first_dup!r}"
        )


def _render_properties_content(
    df: pd.DataFrame,
    *,
    key_col: str,
    value_col: str,
    escaping: str,
) -> str:
    lines: list[str] = []
    for _, row in df.iterrows():
        k = _to_string(row[key_col])
        v = _to_string(row[value_col])
        lines.append(f"{_escape_key(k, escaping)}={_escape_value(v, escaping)}")
    return "\n".join(lines) + "\n" if lines else ""


def _escape_key(s: str, escaping: str) -> str:
    result = _escape_common(s, escaping)
    result = result.replace("=", "\\=").replace(":", "\\:").replace("#", "\\#").replace("!", "\\!")
    if result.startswith(" "):
        result = "\\ " + result[1:]
    return result


def _escape_value(s: str, escaping: str) -> str:
    return _escape_common(s, escaping)


def _escape_common(s: str, escaping: str) -> str:
    s = s.replace("\\", "\\\\")
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    s = s.replace("\t", "\\t")
    if escaping == "unicode":
        chars: list[str] = []
        for ch in s:
            if ord(ch) > 127:
                chars.append(f"\\u{ord(ch):04x}")
            else:
                chars.append(ch)
        s = "".join(chars)
    return s


def _to_string(value: Any) -> str:
    if value is None:
        return ""
    try:
        import pandas as _pd  # noqa: PLC0415
        if _pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def _as_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _require_frame(frames: Mapping[str, Any], name: str) -> pd.DataFrame:
    if name not in frames:
        raise KeyError(f"Frame {name!r} not found")
    frame = frames[name]
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"Frame {name!r} must be a pandas DataFrame")
    return frame


def _ensure_columns(df: pd.DataFrame, columns: Iterable[str], *, frame_name: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"Frame {frame_name!r} is missing columns: {missing!r}")


def _safe_output_dir(output_dir: str | Path) -> Path:
    return Path(output_dir).expanduser().resolve(strict=False)


def _safe_target_path(output_dir: Path, path_label: str) -> Path:
    rel_path = Path(path_label)
    if rel_path.is_absolute():
        raise ValueError(f"Key-value path {path_label!r} must be relative")
    target = (output_dir / rel_path).resolve(strict=False)
    if not target.is_relative_to(output_dir):
        raise ValueError(
            f"Key-value path {path_label!r} escapes output_dir {str(output_dir)!r}"
        )
    return target
