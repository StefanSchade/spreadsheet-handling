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

from . import ingress as domain_ingress
from .meta_bootstrap import deep_merge, get_meta, set_meta


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
    meta = get_meta(frames)

    # Workbook-level defaults
    defaults = overrides.get("defaults")
    if defaults and isinstance(defaults, dict):
        meta = deep_merge(meta, defaults)

    # Per-sheet overrides
    sheet_cfgs = overrides.get("sheets")
    if sheet_cfgs and isinstance(sheet_cfgs, dict):
        # ``get_meta`` intentionally copies only the top-level mapping. Build a
        # separate sheets candidate before merging so a later merge or ingress
        # failure cannot mutate caller-owned per-sheet metadata.
        existing_sheets = meta.get("sheets")
        sheets_meta = {} if existing_sheets is None else dict(existing_sheets)
        for sheet_name, sheet_opts in sheet_cfgs.items():
            if not isinstance(sheet_opts, dict):
                continue
            existing = sheets_meta.get(sheet_name, {})
            sheets_meta[sheet_name] = deep_merge(existing, sheet_opts)
        meta = dict(meta)
        meta["sheets"] = sheets_meta

    # apply_overrides is the other maintained configuration-to-meta boundary:
    # overrides can introduce externally authored workbook metadata, so run the
    # domain ingress coordinator on the merged candidate before writing it
    # back. Automatic internal post-merge enforcement, not a selectable step;
    # The complete candidate is independent of caller-owned mappings;
    # canonicalizing before set_meta keeps every merge/ingress failure atomic.
    canonical = domain_ingress.run_domain_ingress({"_meta": meta}).get("_meta", meta)

    set_meta(frames, canonical)
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
