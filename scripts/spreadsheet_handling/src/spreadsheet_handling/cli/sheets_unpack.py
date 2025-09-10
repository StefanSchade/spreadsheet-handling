#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unpack (Phase 1):
- Workbook (XLSX) oder CSV-Ordner -> mehrere JSON-Dateien.
- MultiIndex-Header werden auf die erste Ebene reduziert.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

import pandas as pd
from spreadsheet_handling.logging_utils import setup_logging, get_logger
from spreadsheet_handling.io_backends import make_backend, JSONBackend

log = get_logger("unpack")

DEFAULT_LEVELS = 3

# ---------- Readers ----------


def _read_xlsx(workbook: Path, levels: int) -> Dict[str, pd.DataFrame]:
    """
    Liest ein XLSX mit EINER Headerzeile (weil wir beim Schreiben flatten)
    und hebt die Spalten wieder in einen MultiIndex mit 'levels' Ebenen an.
    """
    sheets = pd.read_excel(workbook, sheet_name=None, header=0)
    out: Dict[str, pd.DataFrame] = {}
    for name, df in sheets.items():
        # in MultiIndex heben: (col, "", "", ...) auf 'levels'
        cols = list(df.columns)
        tuples = [(c,) + ("",) * (levels - 1) for c in cols]
        df.columns = pd.MultiIndex.from_tuples(tuples)
        out[name] = df
    return out


def _read_csv_folder(folder: Path, levels: int) -> Dict[str, pd.DataFrame]:
    """
    Liest einen Ordner mit {sheet}.csv, erwartet EINE Headerzeile (flattened)
    und hebt die Spalten zurück in einen MultiIndex mit 'levels' Ebenen.
    """
    out: Dict[str, pd.DataFrame] = {}
    for p in sorted(folder.glob("*.csv")):
        df = pd.read_csv(p, header=0, encoding="utf-8")
        cols = list(df.columns)
        tuples = [(c,) + ("",) * (levels - 1) for c in cols]
        df.columns = pd.MultiIndex.from_tuples(tuples)
        out[p.stem] = df
    if not out:
        raise SystemExit(f"Keine *.csv in {folder} gefunden.")
    return out


# ---------- Core ----------


def _rows_from_df(df: pd.DataFrame, helper_prefix: str = "_") -> List[Dict[str, Any]]:
    """
    Reduziert MultiIndex-Header auf erste Ebene, wirft Helper-Spalten (Prefix) weg,
    und gibt Records für JSON zurück.
    """
    first_level = [t[0] for t in df.columns.to_list()]
    df_simple = df.copy()
    df_simple.columns = first_level

    keep_cols = []
    for c in df_simple.columns:
        if isinstance(c, str) and c.startswith(helper_prefix):
            continue
        keep_cols.append(c)
    df_simple = df_simple[keep_cols]

    records = df_simple.where(pd.notnull(df_simple), None).to_dict(orient="records")
    return records


def run_unpack(workbook: Path, out_dir: Path, levels: int, backend: str) -> None:
    src = make_backend(backend)
    frames = src.read_multi(str(workbook), header_levels=levels)
    out = JSONBackend()
    out.write_multi(frames, str(out_dir))
    print(f"[unpack] JSONs geschrieben nach: {out_dir}")


# ---------- CLI ----------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Unpack Workbook -> JSON-Verzeichnis")
    p.add_argument("workbook", help="Pfad zu .xlsx ODER CSV-Ordner")
    p.add_argument("-o", "--output", required=True, help="Zielverzeichnis für JSON-Dateien")
    p.add_argument("--levels", type=int, default=DEFAULT_LEVELS, help="Header-Levels (default 3)")
    p.add_argument(
        "--backend", choices=["xlsx", "csv"], default="xlsx", help="xlsx (default) oder csv"
    )
    p.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logger-Level (default WARNING)",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    setup_logging(args.log_level if hasattr(args, "log_level") else None)

    workbook_path = Path(args.workbook)
    backend = args.backend

    if backend == "xlsx":
        if not workbook_path.exists():
            raise SystemExit(f"Workbook nicht gefunden: {workbook_path}")
    elif backend == "csv":
        if not workbook_path.is_dir():
            raise SystemExit("Für backend=csv muss `workbook` ein Ordner mit *.csv sein.")
    else:
        raise SystemExit(f"Unbekannter Backend-Typ: {backend}")

    log.info("[unpack] writing JSON to %s", args.output)
    run_unpack(workbook_path, Path(args.output), args.levels, backend)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
