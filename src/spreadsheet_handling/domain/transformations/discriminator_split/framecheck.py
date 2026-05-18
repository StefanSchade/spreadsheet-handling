"""Structural frame checks for discriminator split/merge.

Required frame/column presence, source-frame existence, target-frame
collision, and duplicate target-frame rejection. This module performs *no*
conflict reconciliation or precedence resolution: that design space belongs to
FTR-WORKBOOK-VIEW-PAYLOAD-CONFLICT-PRECEDENCE-P6. Verbatim move out of the
former single ``discriminator_split`` module
(FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-DISCRIMINATOR-P5).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd


def _ensure_source_frames_exist(frames: Mapping[str, Any], entries: list[dict[str, Any]]) -> None:
    missing = [entry["frame"] for entry in entries if entry["frame"] not in frames]
    if missing:
        raise KeyError(f"Configured source frame(s) not found: {missing!r}")


def _ensure_no_existing_target_frames(frames: Mapping[str, Any], target_frames: list[str]) -> None:
    collisions = [frame_name for frame_name in target_frames if frame_name in frames]
    if collisions:
        raise ValueError(f"Generated target frame(s) already exist: {collisions!r}")


def _ensure_unique_target_frames(target_frames: Iterable[str]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for frame_name in target_frames:
        if frame_name in seen:
            duplicates.append(frame_name)
        seen.add(frame_name)
    if duplicates:
        raise ValueError(f"Duplicate generated frame name(s): {duplicates!r}")


def _ensure_column(df: pd.DataFrame, column: str, *, frame_name: str) -> None:
    if column not in df.columns:
        raise KeyError(f"Frame {frame_name!r} is missing discriminator column {column!r}")


def _require_frame(frames: Mapping[str, Any], name: str) -> pd.DataFrame:
    if name not in frames:
        raise KeyError(f"Frame {name!r} not found")
    frame = frames[name]
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"Frame {name!r} must be a pandas DataFrame")
    if isinstance(frame.columns, pd.MultiIndex) or any(
        isinstance(col, tuple) for col in frame.columns
    ):
        raise ValueError(f"Frame {name!r} must have flat columns")
    if len(set(frame.columns)) != len(frame.columns):
        raise ValueError(f"Frame {name!r} must not contain duplicate columns")
    return frame
