from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List, NamedTuple

import pandas as pd

from ..frame_keys import iter_data_frames

# Use the shared indexing helpers.
from .indexing import level0_series as _series_from_first_level


FK_PATTERN = re.compile(r"^(?P<id_field>[^_]+)_\((?P<sheet_key>[^)]+)\)$")
HelperValueProvider = Callable[[Any, list[Any]], list[Any]]


class FKDef(NamedTuple):
    fk_column: str  # e.g. "id_(Guten_Morgen)"
    id_field: str  # e.g. "id" or "Schluessel"
    target_sheet_key: str  # e.g. "Guten_Morgen"
    helper_column: str  # e.g. "_Guten_Morgen_name"
    value_field: str  # e.g. "name" or "category"


def _norm_id(v) -> str | None:
    """Normalize IDs to string keys; NaN/None become None."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return str(v)


def normalize_sheet_key(name: str) -> str:
    """Convert whitespace to '_' and reject parentheses."""
    if "(" in name or ")" in name:
        raise ValueError(f"Sheet name contains parentheses, not allowed: {name!r}")
    return re.sub(r"\s+", "_", name.strip())


def assert_no_parentheses_in_columns(df: pd.DataFrame, sheet_name: str) -> None:
    """
    Column headers must not contain parentheses, except for valid FK columns
    matched by FK_PATTERN (for example id_(Guten_Morgen)).
    """
    first = [t[0] if isinstance(t, tuple) else t for t in df.columns.to_list()]
    bad = []
    for c in first:
        if not isinstance(c, str):
            continue
        if "(" in c or ")" in c:
            # FK columns are explicitly allowed.
            if FK_PATTERN.match(c):
                continue
            bad.append(c)
    if bad:
        raise ValueError(
            f"Columns with parentheses on sheet {sheet_name!r} are not allowed "
            f"except for FK columns: {bad}"
        )


def build_registry(
    frames: Dict[str, pd.DataFrame], defaults: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """
    Registry per sheet:
    {
      sheet_key: {
        "sheet_name": original name,
        "id_field": defaults["id_field"] (later overridable per sheet),
        "label_field": defaults["label_field"]
      }
    }
    """
    id_field = str(defaults.get("id_field", "id"))
    label_field = str(defaults.get("label_field", "name"))
    id_field_by_target = defaults.get("id_field_by_target") or {}
    label_field_by_target = defaults.get("label_field_by_target") or {}
    reg: Dict[str, Dict[str, Any]] = {}
    for sheet_name, _df in iter_data_frames(frames):
        key = normalize_sheet_key(sheet_name)
        reg[key] = {
            "sheet_name": sheet_name,
            "id_field": str(
                _target_default(id_field_by_target, key, sheet_name, id_field)
            ),
            "label_field": str(
                _target_default(label_field_by_target, key, sheet_name, label_field)
            ),
        }
    return reg


def _target_default(mapping: Any, sheet_key: str, sheet_name: str, default: str) -> Any:
    if not isinstance(mapping, dict):
        return default
    if sheet_key in mapping:
        return mapping[sheet_key]
    if sheet_name in mapping:
        return mapping[sheet_name]
    return default


def _first_level_columns(df: pd.DataFrame) -> List[str]:
    return [t[0] if isinstance(t, tuple) else t for t in df.columns.to_list()]


def _normalize_helper_fields(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    else:
        values = [str(item) for item in value]
    # Stable de-duplication keeps configured order intact.
    return list(dict.fromkeys(v for v in values if v))


def _resolve_helper_fields(
    fk_column: str,
    sheet_key: str,
    registry: Dict[str, Dict[str, Any]],
    defaults: Dict[str, Any] | None = None,
) -> List[str]:
    defs = defaults or {}
    by_fk = defs.get("helper_fields_by_fk") or {}
    by_target = defs.get("helper_fields_by_target") or {}
    sheet_name = str(registry[sheet_key]["sheet_name"])

    if fk_column in by_fk:
        return _normalize_helper_fields(by_fk[fk_column])
    if sheet_key in by_target:
        return _normalize_helper_fields(by_target[sheet_key])
    if sheet_name in by_target:
        return _normalize_helper_fields(by_target[sheet_name])
    if "helper_fields" in defs:
        return _normalize_helper_fields(defs.get("helper_fields"))

    label_field = str(registry[sheet_key]["label_field"])
    return [label_field]


def detect_fk_columns(
    df: pd.DataFrame,
    registry: Dict[str, Dict[str, Any]],
    helper_prefix: str = "_",
    defaults: Dict[str, Any] | None = None,
) -> List[FKDef]:
    """
    Find columns such as 'id_(Guten_Morgen)' or 'Schluessel_(Guten_Morgen)'.
    Check that the target sheet exists and that id_field matches it strictly.
    """
    fks: List[FKDef] = []
    cols = _first_level_columns(df)
    known_keys = set(registry.keys())
    for c in cols:
        if not isinstance(c, str):
            continue
        m = FK_PATTERN.match(c)
        if not m:
            continue
        id_field = m.group("id_field")
        sheet_key = m.group("sheet_key")
        if sheet_key not in known_keys:
            # FK points at an unknown sheet; ignore it for now.
            continue
        target_id_field = registry[sheet_key]["id_field"]
        if id_field != target_id_field:
            # Strict: only accept matches where the prefix matches the target id_field.
            continue
        helper_fields = _resolve_helper_fields(c, sheet_key, registry, defaults)
        for value_field in helper_fields:
            helper_col = f"{helper_prefix}{sheet_key}_{value_field}"
            fks.append(
                FKDef(
                    fk_column=c,
                    id_field=id_field,
                    target_sheet_key=sheet_key,
                    helper_column=helper_col,
                    value_field=value_field,
                )
            )
    return fks


def build_id_value_maps(
    frames: Dict[str, pd.DataFrame],
    registry: Dict[str, Dict[str, Any]],
    *,
    fields_by_sheet: Dict[str, Iterable[str]] | None = None,
) -> Dict[str, Dict[str, Dict[Any, Any]]]:
    """
    Build nested maps per sheet: {field_name -> {id_value -> field_value}}.
    When `fields_by_sheet` is set, only requested fields are produced.
    """
    maps: Dict[str, Dict[str, Dict[Any, Any]]] = {}
    requested_by_sheet = fields_by_sheet or {}

    for sheet_key, meta in registry.items():
        sheet_name = meta["sheet_name"]
        df = frames[sheet_name]
        id_field = str(meta["id_field"])
        cols = _first_level_columns(df)

        requested = list(
            dict.fromkeys(
                str(field)
                for field in requested_by_sheet.get(
                    sheet_key, [c for c in cols if c != id_field]
                )
                if str(field) and str(field) != id_field
            )
        )
        if id_field not in cols:
            maps[sheet_key] = {field: {} for field in requested}
            continue

        id_series = _series_from_first_level(df, id_field)
        sheet_maps: Dict[str, Dict[Any, Any]] = {}
        for field in requested:
            if field not in cols:
                sheet_maps[field] = {}
                continue
            value_series = _series_from_first_level(df, field)
            field_map: Dict[Any, Any] = {}
            for i, v in zip(id_series.tolist(), value_series.tolist()):
                key = _norm_id(i)
                if key is not None:
                    field_map[key] = v
            sheet_maps[field] = field_map
        maps[sheet_key] = sheet_maps
    return maps


def build_id_label_maps(
    frames: Dict[str, pd.DataFrame], registry: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[Any, Any]]:
    """
    Build one map per sheet: {id_value -> label_value}.
    Use id_field and label_field from the registry; missing fields produce empty maps.
    """
    fields_by_sheet = {
        sheet_key: [str(meta["label_field"])] for sheet_key, meta in registry.items()
    }
    value_maps = build_id_value_maps(frames, registry, fields_by_sheet=fields_by_sheet)
    maps: Dict[str, Dict[Any, Any]] = {}
    for sheet_key, meta in registry.items():
        label_field = str(meta["label_field"])
        maps[sheet_key] = value_maps.get(sheet_key, {}).get(label_field, {})
    return maps


def build_id_sets(
    frames: Dict[str, pd.DataFrame],
    registry: Dict[str, Dict[str, Any]],
) -> Dict[str, set[str]]:
    """Return existing IDs per sheet as normalized string sets."""
    id_sets: Dict[str, set[str]] = {}
    for sheet_key, meta in registry.items():
        sheet_name = meta["sheet_name"]
        df = frames[sheet_name]
        id_field = str(meta["id_field"])
        cols = _first_level_columns(df)
        if id_field not in cols:
            id_sets[sheet_key] = set()
            continue
        ids = _series_from_first_level(df, id_field)
        id_sets[sheet_key] = {
            key for key in (_norm_id(value) for value in ids.tolist()) if key is not None
        }
    return id_sets


def apply_fk_helpers(
    df: pd.DataFrame,
    fk_defs: List[FKDef],
    id_value_maps: Dict[str, Any],
    levels: int,
    helper_prefix: str = "_",
    helper_value_provider: HelperValueProvider | None = None,
) -> pd.DataFrame:
    if not fk_defs:
        return df

    first_cols = _first_level_columns(df)
    new_df = df.copy()

    for fk in fk_defs:
        # Support FKDef and legacy dict inputs.
        if isinstance(fk, dict):
            fk_col = fk["column"]  # e.g. "id_(A)"
            target_key = fk.get("target_key") or fk.get("target_sheet_key")
            value_field = str(fk.get("value_field", "name"))
            helper_col = str(
                fk.get("helper_column") or f"{helper_prefix}{target_key}_{value_field}"
            )
        else:
            fk_col = fk.fk_column
            target_key = fk.target_sheet_key
            helper_col = fk.helper_column
            value_field = fk.value_field

        # Avoid duplicates.
        if helper_col in first_cols:
            continue

        target_maps = id_value_maps.get(target_key, {})
        if isinstance(target_maps, dict) and target_maps and all(
            isinstance(v, dict) for v in target_maps.values()
        ):
            value_map = target_maps.get(value_field, {})
        elif isinstance(target_maps, dict):
            # Backward-compatible path for older callers that still pass a flat id->label map.
            value_map = target_maps
        else:
            value_map = {}

        # Pull FK values from level 0, not as a DataFrame.
        fk_series = _series_from_first_level(new_df, fk_col)
        raw_ids = fk_series.tolist()

        if helper_value_provider is None:
            values = []
            for rid in raw_ids:
                lbl = value_map.get(_norm_id(rid))
                values.append(lbl)
        else:
            values = helper_value_provider(fk, raw_ids)

        # Add a new column as a MultiIndex tuple of matching length.
        col_tuple = (helper_col,) + ("",) * (levels - 1)
        new_df[col_tuple] = values

    return new_df
