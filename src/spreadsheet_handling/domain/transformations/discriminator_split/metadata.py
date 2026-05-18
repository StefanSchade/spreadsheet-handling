"""Canonical ``split_by_discriminator`` metadata read/write plumbing.

``_META_KEY`` is a canonical, persisted, roundtrip-relevant meta contract
string (profile-locked by ``test_meta_registry_hardening``); it and the
read/write helpers are moved verbatim out of the former single
``discriminator_split`` module
(FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-DISCRIMINATOR-P5). The metadata payload
literals deliberately stay inline in ``split``/``merge``; this module only does
the read/write plumbing and owns no payload shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_META_KEY = "split_by_discriminator"


def _split_meta(frames: Mapping[str, Any], config_id: str) -> Mapping[str, Any] | None:
    meta = frames.get("_meta")
    if not isinstance(meta, Mapping):
        return None
    configs = meta.get(_META_KEY)
    if not isinstance(configs, Mapping):
        return None
    config = configs.get(config_id)
    return config if isinstance(config, Mapping) else None


def _write_split_meta(
    out: dict[str, Any],
    *,
    config_id: str,
    payload: dict[str, Any],
) -> None:
    meta = dict(out.get("_meta") or {})
    configs = dict(meta.get(_META_KEY) or {})
    configs[config_id] = payload
    meta[_META_KEY] = configs
    out["_meta"] = meta
