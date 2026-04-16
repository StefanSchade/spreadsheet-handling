"""Load and apply per-sheet configuration overrides from YAML.

Implements FTR-YAML-OVERRIDES: analysts can define sheet-specific options
(id_field, helper_prefix, auto_filter, freeze_header, etc.) in a YAML file
instead of repeating them on the CLI.

The YAML schema is::

    defaults:                       # optional workbook-level defaults
      auto_filter: true
      freeze_header: false

    sheets:
      Kunden:
        id_field: kunden_id
        helper_prefix: "_"
        auto_filter: true
      Bestellungen:
        id_field: bestellnr
        freeze_header: true

Precedence (aligned with FTR-META-BOOTSTRAP):
  Defaults < per-sheet YAML < CLI overrides
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from .meta_bootstrap import _deep_merge, _get_meta, _set_meta


def load_overrides(path: str | Path) -> Dict[str, Any]:
    """Read a YAML overrides file and return the parsed dict.

    Returns ``{"defaults": {...}, "sheets": {...}}`` — both keys optional.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Overrides file not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Overrides file must be a YAML mapping, got {type(raw).__name__}")
    return raw


def apply_overrides(
    frames: Any,
    overrides: Dict[str, Any],
) -> Any:
    """Merge *overrides* into frames meta.

    - ``overrides["defaults"]`` is merged into the workbook-level meta.
    - ``overrides["sheets"][name]`` is stored under
      ``meta["sheets"][name]`` where the composer can pick it up
      for ``SheetIR.meta["options"]``.

    Returns *frames* (mutated in place).
    """
    meta = _get_meta(frames)

    # Workbook-level defaults
    defaults = overrides.get("defaults")
    if defaults and isinstance(defaults, dict):
        meta = _deep_merge(meta, defaults)

    # Per-sheet overrides
    sheet_cfgs = overrides.get("sheets")
    if sheet_cfgs and isinstance(sheet_cfgs, dict):
        sheets_meta = meta.setdefault("sheets", {})
        for sheet_name, sheet_opts in sheet_cfgs.items():
            if not isinstance(sheet_opts, dict):
                continue
            existing = sheets_meta.get(sheet_name, {})
            sheets_meta[sheet_name] = _deep_merge(existing, sheet_opts)

    _set_meta(frames, meta)
    return frames


def load_and_apply_overrides(
    frames: Any,
    *,
    overrides_path: str | Path | None = None,
    overrides: Dict[str, Any] | None = None,
) -> Any:
    """Resolve overrides from inline config or path, then apply them.

    This is a domain-facing convenience entry point for pipeline binding.
    """
    resolved = overrides
    if resolved is None and overrides_path:
        resolved = load_overrides(overrides_path)
    if resolved:
        return apply_overrides(frames, resolved)
    return frames
