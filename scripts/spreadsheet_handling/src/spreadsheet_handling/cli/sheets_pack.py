#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pack (Phase 1):
- Mehrere JSON-Quellen -> ein Workbook (XLSX) oder ein CSV-Ordner.
- Noch keine FK-/Helper-/Formel-Logik.
"""
from __future__ import annotations

import argparse
import json
import pandas as pd

from pathlib import Path
from typing import Any, Dict, List, Optional

from spreadsheet_handling.core.fk import (
    build_registry,
    build_id_label_maps,
    detect_fk_columns,
    apply_fk_helpers,
    assert_no_parentheses_in_columns,
    normalize_sheet_key,
)

DEFAULTS: Dict[str, Any] = {
    "levels": 3,
    "backend": "xlsx",      # xlsx|csv
    "id_field": "id",       # ID-Feld in Zielblättern
    "label_field": "name",  # menschenlesbares Label
    "helper_prefix": "_",
    "detect_fk": True,
}


# ---------- Utilities ----------


def _ensure_multiindex(df: pd.DataFrame, levels: int) -> pd.DataFrame:
    """
    Stellt sicher, dass df.columns ein MultiIndex mit 'levels' Ebenen ist.
    Wenn flache Spaltennamen vorliegen, wird die erste Ebene belegt und der Rest mit "" aufgefüllt.
    """
    if isinstance(df.columns, pd.MultiIndex):
        # ggf. auf die gewünschte Level-Anzahl auffüllen
        if df.columns.nlevels < levels:
            new_tuples = []
            for tpl in df.columns.to_list():
                if not isinstance(tpl, tuple):
                    tpl = (tpl,)
                fill = ("",) * (levels - len(tpl))
                new_tuples.append(tuple(tpl) + fill)
            df.columns = pd.MultiIndex.from_tuples(new_tuples)
        return df

    cols = list(df.columns)
    tuples = [(c,) + ("",) * (levels - 1) for c in cols]
    df.columns = pd.MultiIndex.from_tuples(tuples)
    return df


def _read_json_records(path: Path) -> List[Dict[str, Any]]:
    """
    Liest eine JSON-Datei. Erlaubt als Root entweder Liste[Objekt] oder einzelnes Objekt.
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError(f"Unsupported JSON root in {path}: {type(data)}")


# ---------- Config Handling ----------


def _load_config(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Lädt YAML-Config (wenn --config gesetzt) oder baut eine ad-hoc-Konfiguration
    aus <input-dir> und -o/--output.

    Schema (v1):
    {
      workbook: str,
      defaults: {levels:int, backend:str},
      sheets: [ {name:str, json:str} | {json:str(dir)} ]
    }
    """
    if args.config:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("PyYAML ist nicht installiert. Bitte `pip install pyyaml`.") from exc

        with open(args.config, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        # Defaults mergen
        dfl = DEFAULTS.copy()
        dfl.update((cfg.get("defaults") or {}))
        cfg["defaults"] = dfl

        if not cfg.get("workbook"):
            if not args.output:
                raise SystemExit("`workbook` fehlt (YAML) und -o/--output ist nicht gesetzt.")
            cfg["workbook"] = args.output
        return cfg

    # No-YAML-Modus
    if not args.input or not args.output:
        raise SystemExit("Ohne --config brauchst du <json_dir> und -o <workbook>.")

    json_dir = Path(args.input)
    if not json_dir.is_dir():
        raise SystemExit(f"{json_dir} ist kein Verzeichnis")

    backend = args.backend or DEFAULTS["backend"]
    cfg = {
        "workbook": args.output,
        "defaults": {
            "levels": args.levels or DEFAULTS["levels"],
            "backend": backend,
        },
        "sheets": [],
    }

    # Jede *.json Datei wird ein Blatt
    for p in sorted(json_dir.glob("*.json")):
        cfg["sheets"].append({"name": p.stem, "json": str(p)})

    if not cfg["sheets"]:
        raise SystemExit(f"Keine *.json Dateien in {json_dir} gefunden.")
    return cfg


# ---------- Writer ----------

def _write_xlsx(workbook_path: Path, frames: Dict[str, pd.DataFrame]) -> None:
    """
    Excel: MultiIndex-Spalten robust schreiben, indem wir die Spalten
    vor dem Schreiben auf die 1. Ebene flatten (eine Headerzeile).
    """
    workbook_path = workbook_path.with_suffix(".xlsx")
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as xw:
        for sheet, df in frames.items():
            df_out = df.copy()
            if isinstance(df_out.columns, pd.MultiIndex):
                # nur die erste Ebene verwenden (Level 0)
                df_out.columns = [t[0] for t in df_out.columns.to_list()]
            df_out.to_excel(xw, sheet_name=sheet, index=False)

def _write_csv_folder(out_dir: Path, frames: Dict[str, pd.DataFrame]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for sheet, df in frames.items():
        (out_dir / f"{sheet}.csv").write_text("", encoding="utf-8")  # ensure file exists/owned
        df.to_csv(out_dir / f"{sheet}.csv", index=False, encoding="utf-8")


# ---------- Core ----------


def run_pack(cfg: Dict[str, Any]) -> None:
    defaults = cfg.get("defaults", {})
    levels = int(defaults.get("levels", DEFAULTS["levels"]))
    backend = (defaults.get("backend") or DEFAULTS["backend"]).lower()

    frames: Dict[str, pd.DataFrame] = {}

    for sheet_cfg in cfg.get("sheets", []):
        src = Path(sheet_cfg["json"])  # Datei ODER Verzeichnis
        if src.is_dir():
            # Erzeuge je Datei ein Blatt (Name=Stem)
            for p in sorted(src.glob("*.json")):
                records = _read_json_records(p)
                df = pd.DataFrame(records)
                df = _ensure_multiindex(df, levels)
                frames[p.stem] = df
        else:
            name = sheet_cfg.get("name") or src.stem
            records = _read_json_records(src)
            df = pd.DataFrame(records)
            df = _ensure_multiindex(df, levels)
            frames[name] = df

    # --- Validierung: keine Klammern in Spalten; Sheet-Key-Registry bauen ---
    for sheet_name, df in frames.items():
        assert_no_parentheses_in_columns(df, sheet_name)

    registry = build_registry(frames, defaults)
    id_maps = build_id_label_maps(frames, registry)

    if bool(defaults.get("detect_fk", True)):
        helper_prefix = str(defaults.get("helper_prefix", "_"))
        for sheet_name, df in list(frames.items()):
            fk_defs = detect_fk_columns(df, registry, helper_prefix=helper_prefix)
            if not fk_defs:
                continue
            levels = int(defaults.get("levels", DEFAULTS["levels"]))
            frames[sheet_name] = apply_fk_helpers(
                df, fk_defs, id_maps, levels=levels, helper_prefix=helper_prefix
            )

    out = cfg.get("workbook")
    if not out:
        raise SystemExit("Output-Pfad `workbook` fehlt.")
    out_path = Path(out)

    if backend == "xlsx":
        _write_xlsx(out_path, frames)
        print(f"[pack] XLSX geschrieben: {out_path.with_suffix('.xlsx')}")
    elif backend == "csv":
        # out kann Datei- oder Ordnername sein -> immer zu Ordner normalisieren
        if out_path.suffix:
            out_path = out_path.parent / out_path.stem
        _write_csv_folder(out_path, frames)
        print(f"[pack] CSV-Ordner geschrieben: {out_path}")
    else:
        raise SystemExit(f"Unbekannter Backend-Typ: {backend}")


# ---------- CLI ----------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Pack JSON -> Workbook (Multi-Sheet)")
    p.add_argument("input", nargs="?", help="JSON-Verzeichnis (no-YAML-Modus)")
    p.add_argument("-o", "--output", help="Workbook-Pfad (xlsx) oder Ordner (csv)")
    p.add_argument("--config", help="YAML-Konfiguration")
    p.add_argument("--levels", type=int, default=None, help="Header-Levels (default 3)")
    p.add_argument("--backend", choices=["xlsx", "csv"], help="xlsx (default) oder csv")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    cfg = _load_config(args)
    run_pack(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
