from __future__ import annotations
import re
from typing import Any, Dict, List, NamedTuple
import pandas as pd
# Neu: zentrale Indexing-Helpers verwenden
from .indexing import has_level0 as _has_level0, level0_series as _series_from_first_level


FK_PATTERN = re.compile(r"^(?P<id_field>[^_]+)_\((?P<sheet_key>[^)]+)\)$")


class FKDef(NamedTuple):
    fk_column: str  # z. B. "id_(Guten_Morgen)"
    id_field: str  # z. B. "id" oder "Schluessel"
    target_sheet_key: str  # z. B. "Guten_Morgen"
    helper_column: str  # z. B. "_Guten_Morgen_name"


def _norm_id(v) -> str | None:
    """Normalisiert IDs auf String-Schlüssel; NaN/None -> None."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return str(v)


def normalize_sheet_key(name: str) -> str:
    """Leerzeichen -> '_'; prüft, dass keine Klammern vorkommen."""
    if "(" in name or ")" in name:
        raise ValueError(f"Blattname enthält Klammern, nicht erlaubt: {name!r}")
    return re.sub(r"\s+", "_", name.strip())


def assert_no_parentheses_in_columns(df: pd.DataFrame, sheet_name: str) -> None:
    """
    Spaltenüberschriften dürfen KEINE Klammern enthalten – mit Ausnahme
    von korrekt gematchten FK-Spalten gemäß FK_PATTERN (z. B. id_(Guten_Morgen)).
    """
    first = [t[0] if isinstance(t, tuple) else t for t in df.columns.to_list()]
    bad = []
    for c in first:
        if not isinstance(c, str):
            continue
        if "(" in c or ")" in c:
            # FK-Spalten sind explizit erlaubt
            if FK_PATTERN.match(c):
                continue
            bad.append(c)
    if bad:
        raise ValueError(
            f"Spalten mit Klammern in Blatt {sheet_name!r} nicht erlaubt (außer FK-Spalten): {bad}"
        )


def build_registry(
    frames: Dict[str, pd.DataFrame], defaults: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """
    Registry pro Sheet:
    {
      sheet_key: {
        "sheet_name": originaler Name,
        "id_field": defaults["id_field"] (später pro Sheet überschreibbar),
        "label_field": defaults["label_field"]
      }
    }
    """
    id_field = str(defaults.get("id_field", "id"))
    label_field = str(defaults.get("label_field", "name"))
    reg: Dict[str, Dict[str, Any]] = {}
    for sheet_name, _df in frames.items():
        key = normalize_sheet_key(sheet_name)
        reg[key] = {
            "sheet_name": sheet_name,
            "id_field": id_field,
            "label_field": label_field,
        }
    return reg


def _first_level_columns(df: pd.DataFrame) -> List[str]:
    return [t[0] if isinstance(t, tuple) else t for t in df.columns.to_list()]

def detect_fk_columns(
    df: pd.DataFrame, registry: Dict[str, Dict[str, Any]], helper_prefix: str = "_"
) -> List[FKDef]:
    """
    Findet Spalten wie 'id_(Guten_Morgen)' bzw. 'Schluessel_(Guten_Morgen)'.
    Prüft, dass target_sheet existiert und (strikt) dass id_field zum Zielblatt passt.
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
            # FK zeigt auf unbekanntes Blatt -> ignorieren (oder warnen)
            continue
        target_id_field = registry[sheet_key]["id_field"]
        if id_field != target_id_field:
            # Strikt: nur akzeptieren, wenn Prefix zum Zielblatt-id_field passt
            # (alternativ: akzeptieren & trotzdem target_id_field verwenden)
            continue
        helper_col = f"{helper_prefix}{sheet_key}_name"
        fks.append(
            FKDef(
                fk_column=c, id_field=id_field, target_sheet_key=sheet_key, helper_column=helper_col
            )
        )
    return fks


def build_id_label_maps(
    frames: Dict[str, pd.DataFrame], registry: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[Any, Any]]:
    """
    Für jedes Sheet eine Map: {id_value -> label_value}.
    Nimmt id_field & label_field aus Registry. Fehlende Felder -> leere Map.
    """
    maps: Dict[str, Dict[Any, Any]] = {}
    for sheet_key, meta in registry.items():
        sheet_name = meta["sheet_name"]
        df = frames[sheet_name]
        id_field = meta["id_field"]
        label_field = meta["label_field"]
        cols = _first_level_columns(df)
        if id_field not in cols or label_field not in cols:
            maps[sheet_key] = {}
            continue
        id_series = _series_from_first_level(df, id_field)
        label_series = _series_from_first_level(df, label_field)
        # robust gegen keys mit NaN oder Typunterschieden
        m: Dict[Any, Any] = {}
        for i, v in zip(id_series.tolist(), label_series.tolist()):
            key = _norm_id(i)
            if key is not None:
                m[key] = v
        maps[sheet_key] = m
    return maps


# in scripts/spreadsheet_handling/src/spreadsheet_handling/core/fk.py


def apply_fk_helpers(
    df: pd.DataFrame,
    fk_defs: List[FKDef],
    id_label_maps: Dict[str, Dict[Any, Any]],
    levels: int,
    helper_prefix: str = "_",
) -> pd.DataFrame:
    if not fk_defs:
        return df

    first_cols = _first_level_columns(df)
    new_df = df.copy()

    for fk in fk_defs:
        # --- FKDef ODER dict robust unterstützen ---
        if isinstance(fk, dict):
            fk_col = fk["column"]  # z.B. "id_(A)"
            target_key = fk.get("target_key") or fk.get("target_sheet_key")
            helper_col = f"{helper_prefix}{target_key}_name"
        else:
            fk_col = fk.fk_column
            target_key = fk.target_sheet_key
            helper_col = fk.helper_column
        # -------------------------------------------

        # nicht duplizieren
        if helper_col in first_cols:
            continue

        label_map = id_label_maps.get(target_key, {})

        # FK-Werte aus Level-0 holen (nicht DataFrame!)
        fk_series = _series_from_first_level(new_df, fk_col)
        raw_ids = fk_series.tolist()

        # robustes Lookup mit Normalisierung
        values = []
        for rid in raw_ids:
            lbl = label_map.get(_norm_id(rid))
            values.append(lbl)

        # neue Spalte als MultiIndex-Tuple gleicher Länge
        col_tuple = (helper_col,) + ("",) * (levels - 1)
        new_df[col_tuple] = values

    return new_df
