"""Relation-key-aware value provider construction for FK helpers."""
from __future__ import annotations

from typing import Any

from ....core.fk import FKDef, HelperValueProvider
from ....core.indexing import level0_series
from ....domain.relation_keys import RelationKeyIdentity, relation_key_identity


def build_relation_key_value_provider(
    frames: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    fields_by_sheet: dict[str, list[str]],
) -> HelperValueProvider:
    """Build a provider that resolves FK values through Domain key identity.

    Pandas dtype rules and Core's legacy string keys do not express relation
    identity.  The provider therefore maps only owner-defined eligible keys;
    ``_materialize_fk_helpers`` remains responsible only for column mechanics.
    """
    value_maps = _build_relation_key_value_maps(frames, registry, fields_by_sheet)

    def provider(fk: FKDef, source_keys: list[Any]) -> list[Any]:
        target_maps = value_maps.get(fk.target_sheet_key, {})
        value_map = target_maps.get(fk.value_field, {})
        values: list[Any] = []
        for source_key in source_keys:
            identity = relation_key_identity(source_key)
            values.append("" if identity is None else value_map.get(identity, ""))
        return values

    return provider


def _build_relation_key_value_maps(
    frames: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    fields_by_sheet: dict[str, list[str]],
) -> dict[str, dict[str, dict[RelationKeyIdentity, Any]]]:
    maps: dict[str, dict[str, dict[RelationKeyIdentity, Any]]] = {}
    for sheet_key, target in registry.items():
        frame = frames.get(str(target["sheet_name"]))
        if frame is None:
            maps[sheet_key] = {}
            continue
        id_field = str(target["id_field"])
        fields = fields_by_sheet.get(sheet_key, [])
        target_maps: dict[str, dict[RelationKeyIdentity, Any]] = {}
        try:
            identifiers = level0_series(frame, id_field).tolist()
        except KeyError:
            maps[sheet_key] = {field: {} for field in fields}
            continue
        for field in fields:
            try:
                values = level0_series(frame, field).tolist()
            except KeyError:
                target_maps[field] = {}
                continue
            field_map: dict[RelationKeyIdentity, Any] = {}
            for identifier, value in zip(identifiers, values):
                identity = relation_key_identity(identifier)
                if identity is not None:
                    field_map[identity] = value
            target_maps[field] = field_map
        maps[sheet_key] = target_maps
    return maps
