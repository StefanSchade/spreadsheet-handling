from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional

import pandas as pd

Frames = Dict[str, pd.DataFrame]
Step = Callable[[Frames], Frames]


@dataclass(frozen=True)
class MarkHelpersConfig:
    sheet: Optional[str]
    cols: Iterable[str]
    prefix: str = "_"


def mark_helpers(sheet: Optional[str], cols: Iterable[str], prefix: str = "_") -> Step:
    """
    Kennzeichnet angegebene Spalten als Hilfsspalten, indem sie umbenannt werden (Prefix).
    - sheet=None → auf allen Sheets, falls die Spalten dort existieren
    - keine Seiteneffekte auf andere Sheets
    """
    cfg = MarkHelpersConfig(sheet=sheet, cols=tuple(cols), prefix=prefix)

    def _step(frames: Frames) -> Frames:
        out: Frames = {}
        for name, df in frames.items():
            if cfg.sheet is not None and name != cfg.sheet:
                out[name] = df
                continue

            if df.empty or df.columns.empty:
                out[name] = df
                continue

            rename_map: Dict[str, str] = {}
            for c in cfg.cols:
                if c in df.columns and not str(c).startswith(cfg.prefix):
                    rename_map[c] = f"{cfg.prefix}{c}"

            out[name] = df.rename(columns=rename_map)
        return out

    return _step


@dataclass(frozen=True)
class CleanAuxColumnsConfig:
    sheet: Optional[str] = None
    drop_roles: tuple[str, ...] = ("helper",)
    drop_prefixes: tuple[str, ...] = ("_", "helper__", "fk__")


def clean_aux_columns(
    sheet: Optional[str] = None,
    *,
    drop_roles: Iterable[str] = ("helper",),
    drop_prefixes: Iterable[str] = ("_", "helper__", "fk__"),
) -> Step:
    """
    Entfernt Hilfsspalten anhand von Präfixen (Fallback-Strategie).
    (Metadaten-basierte Rolle kann später integriert werden; Signatur ist bereits vorbereitet.)
    """
    cfg = CleanAuxColumnsConfig(
        sheet=sheet,
        drop_roles=tuple(drop_roles),
        drop_prefixes=tuple(drop_prefixes),
    )

    def _step(frames: Frames) -> Frames:
        def _is_aux(col: str) -> bool:
            col_s = str(col)
            return any(col_s.startswith(p) for p in cfg.drop_prefixes)

        out: Frames = {}
        for name, df in frames.items():
            if cfg.sheet is not None and name != cfg.sheet:
                out[name] = df
                continue
            if df.empty or df.columns.empty:
                out[name] = df
                continue

            keep = [c for c in df.columns if not _is_aux(str(c))]
            out[name] = df.loc[:, keep]
        return out

    return _step
