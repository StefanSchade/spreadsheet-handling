"""Artifact manifest aggregation for pipeline writer report frames.

Merges report frames emitted by writer steps into a deterministic shared-shape
manifest frame and optionally writes a YAML or JSON manifest artifact.

This module is observational only — no build orchestration, no lifecycle
management, no implicit dependencies between pipeline executions.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

Frames = dict[str, Any]

MANIFEST_COLUMNS = [
    "path",
    "artifact_kind",
    "writer_step",
    "source_frames",
    "row_count",
    "checksum",
    "status",
]

_VALID_CHECKSUMS = {"sha256"}


def write_artifact_manifest(
    frames: Mapping[str, Any],
    *,
    reports: list[str | Mapping[str, Any]],
    output: str = "generated_artifacts",
    output_dir: str | Path | None = None,
    manifest_path: str | None = None,
    checksum: str | None = None,
    name: str | None = None,
) -> Frames:
    """Merge writer report frames into a deterministic shared-shape manifest.

    ``reports`` accepts a list of plain frame-name strings or annotation dicts::

        reports:
          - structured_yaml_files
          - frame: key_value_resource_files
            writer_step: write_key_value_resources
            artifact_kind: properties

    ``manifest_path`` must be relative to ``output_dir``.  Absolute paths and
    directory traversal are rejected.  ``output_dir`` is required when either
    ``manifest_path`` or ``checksum`` is set.

    ``checksum`` may be ``None`` (default) or ``"sha256"``.  Checksums are
    computed over raw file bytes, making them independent of platform newline
    translation.
    """
    del name
    if checksum is not None and checksum not in _VALID_CHECKSUMS:
        raise ValueError(
            f"Unsupported checksum {checksum!r}; expected one of {sorted(_VALID_CHECKSUMS)!r}"
        )
    if (checksum is not None or manifest_path is not None) and output_dir is None:
        raise ValueError(
            "output_dir is required when checksum or manifest_path is set"
        )

    out_dir = _safe_output_dir(output_dir) if output_dir is not None else None

    specs = [_parse_report_spec(entry) for entry in reports]

    all_rows: list[dict[str, Any]] = []
    for frame_name, writer_step, artifact_kind in specs:
        df = _require_frame(frames, frame_name)
        _ensure_path_column(df, frame_name=frame_name)
        all_rows.extend(_normalize_report_rows(df, frame_name=frame_name, writer_step=writer_step, artifact_kind=artifact_kind))

    all_rows.sort(key=lambda r: (r["path"], r["writer_step"]))

    _check_duplicate_paths(all_rows)

    if checksum is not None and out_dir is not None:
        for row in all_rows:
            file_path = out_dir / row["path"]
            row["checksum"] = _sha256_of_file(file_path)

    manifest_df = pd.DataFrame(all_rows, columns=MANIFEST_COLUMNS)

    if manifest_path is not None and out_dir is not None:
        target = _safe_target_path(out_dir, manifest_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        records = _manifest_to_records(manifest_df)
        _write_manifest_file(target, records)

    out = dict(frames)
    out[output] = manifest_df
    return out


def _parse_report_spec(
    entry: str | Mapping[str, Any],
) -> tuple[str, str, str]:
    if isinstance(entry, str):
        return entry, "", ""
    if not isinstance(entry, Mapping):
        raise TypeError(f"Each reports entry must be a string or mapping, got {type(entry).__name__!r}")
    frame_name = entry.get("frame")
    if not isinstance(frame_name, str) or not frame_name.strip():
        raise ValueError("Each reports mapping must have a non-empty 'frame' key")
    writer_step = str(entry.get("writer_step") or "")
    artifact_kind = str(entry.get("artifact_kind") or "")
    return frame_name, writer_step, artifact_kind


def _normalize_report_rows(
    df: pd.DataFrame,
    *,
    frame_name: str,
    writer_step: str,
    artifact_kind: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        if "source_frames" in df.columns:
            raw_sf = row["source_frames"]
            source_frames: list[str] = (
                list(raw_sf) if isinstance(raw_sf, (list, tuple))
                else [str(raw_sf)]
            )
        elif "frame" in df.columns:
            source_frames = [str(row["frame"])]
        else:
            source_frames = []

        row_count = int(row["rows"]) if "rows" in df.columns else 0

        rows.append({
            "path": str(row["path"]),
            "artifact_kind": artifact_kind,
            "writer_step": writer_step,
            "source_frames": source_frames,
            "row_count": row_count,
            "checksum": "",
            "status": "success",
        })
    return rows


def _check_duplicate_paths(rows: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for row in rows:
        path = row["path"]
        if path in seen:
            raise ValueError(f"Duplicate artifact path in manifest: {path!r}")
        seen.add(path)


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _manifest_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        records.append({
            "path": row["path"],
            "artifact_kind": row["artifact_kind"],
            "writer_step": row["writer_step"],
            "source_frames": list(row["source_frames"]),
            "row_count": int(row["row_count"]),
            "checksum": row["checksum"],
            "status": row["status"],
        })
    return records


def _write_manifest_file(target: Path, records: list[dict[str, Any]]) -> None:
    suffix = target.suffix.lower()
    with target.open("w", encoding="utf-8", newline="\n") as fh:
        if suffix == ".json":
            json.dump(records, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        else:
            yaml.safe_dump(records, fh, sort_keys=False, allow_unicode=True, default_flow_style=False, width=4096)


def _require_frame(frames: Mapping[str, Any], name: str) -> pd.DataFrame:
    if name not in frames:
        raise KeyError(f"Report frame {name!r} not found in frames")
    frame = frames[name]
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"Report frame {name!r} must be a pandas DataFrame")
    return frame


def _ensure_path_column(df: pd.DataFrame, *, frame_name: str) -> None:
    if "path" not in df.columns:
        raise KeyError(f"Report frame {frame_name!r} is missing required column 'path'")


def _safe_output_dir(output_dir: str | Path) -> Path:
    return Path(output_dir).expanduser().resolve(strict=False)


def _safe_target_path(output_dir: Path, path_label: str) -> Path:
    rel_path = Path(path_label)
    if rel_path.is_absolute():
        raise ValueError(f"Manifest path {path_label!r} must be relative")
    target = (output_dir / rel_path).resolve(strict=False)
    if not target.is_relative_to(output_dir):
        raise ValueError(
            f"Manifest path {path_label!r} escapes output_dir {str(output_dir)!r}"
        )
    return target
