from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import BackendOptions

Frames = Mapping[str, Any]


def save_discard(
    frames: Frames,
    path: str,
    *,
    options: Mapping[str, Any] | BackendOptions | None = None,
) -> None:
    """Accept a frame payload and intentionally write no output artifact."""
    _ = (frames, path, options)
