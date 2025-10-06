from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional

import re
import pandas as pd

from ...pipeline.types import Step, Frames

Frames = Dict[str, pd.DataFrame]
Step = Callable[[Frames], Frames]

_FK_RE = re.compile(r"^id_\((.+)\)$")  # z.B. id_(branch) -> "branch"

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

from typing import Tuple

def _flatten_header_to_level0(df: pd.DataFrame) -> pd.DataFrame:
    cols_in = list(df.columns)
    cols_out = [(c[0] if isinstance(c, tuple) and len(c) else c) for c in cols_in]
    if cols_in == cols_out:
        return df
    out = df.copy()
    out.columns = cols_out
    return out

def flatten_headers(sheet: Optional[str] = None, *, mode: str = "first_nonempty", sep: str = "") -> Step:
    def _step(frames: Frames) -> Frames:
        out: Frames = {}
        for name, df in frames.items():
            if sheet is not None and name != sheet:
                out[name] = df; continue
            cols = list(df.columns)
            has_tuples = any(isinstance(c, tuple) for c in cols)
            if not isinstance(df.columns, pd.MultiIndex) and not has_tuples:
                out[name] = df; continue

            tuples = [tuple(c) if isinstance(c, tuple) else (str(c),) for c in cols]
            if mode == "level0":
                new = [str(t[0]) for t in tuples]
            elif mode == "join":
                new = [sep.join(str(x) for x in t if str(x)) for t in tuples]
            else:  # first_nonempty
                new = [next((str(x) for x in t if str(x)), "") for t in tuples]

            nd = df.copy(); nd.columns = new
            out[name] = nd
        return out
    return _step


# --- NEW: reorder helpers right after their FK column --------------------------------
import re
_FK_RE = re.compile(r"^id_\((.+)\)$")  # matches id_(branch) -> "branch"


def _first_nonempty_label(col: object) -> str:
    """
    Liefert die sichtbare Bezeichnung einer Spalte:
    - bei MultiIndex: erstes nicht-leeres Level als String
    - sonst: str(col)
    """
    if isinstance(col, tuple):
        for x in col:
            s = str(x)
            if s:
                return s
        return ""  # alles leer
    return str(col)

def reorder_helpers_next_to_fk(
        sheet: Optional[str] = None,
        *,
        helper_prefix: str = "_"
) -> Step:
    """
    Verschiebt Helper-Spalten, die zu einer FK-Spalte gehören, unmittelbar hinter diese FK.
    Heuristik:
      - FK heißt id_(<target>)
      - passende Helper heißen f"{helper_prefix}{<target>}_*"
    Funktioniert sowohl mit normalen Spalten als auch mit MultiIndex-Spalten.
    """
    def _step(frames: Frames) -> Frames:
        out: Frames = {}
        for name, df in frames.items():
            if sheet is not None and name != sheet:
                out[name] = df
                continue
            if df.empty:
                out[name] = df
                continue

            # Arbeitsliste der Spalten + Lookup von "sichtbaren" Labels
            cols = list(df.columns)
            labels: Dict[object, str] = {c: _first_nonempty_label(c) for c in cols}

            # Positionen schneller nachschlagen
            def rebuild_index():
                return {c: i for i, c in enumerate(cols)}
            colpos = rebuild_index()

            moved = set()

            for c in list(cols):
                label = labels[c]
                m = _FK_RE.match(label)
                if not m:
                    continue
                target = m.group(1)  # z.B. "branch"
                fk_ix = colpos.get(c, -1)
                if fk_ix < 0:
                    continue

                # alle Helper, deren sichtbares Label mit f"_{target}_" beginnt
                helpers = [
                    h for h in cols
                    if h not in moved and labels.get(h, "").startswith(f"{helper_prefix}{target}_")
                ]

                # direkt hinter die FK spalte(n) einfügen (stabile Reihenfolge)
                for k, h in enumerate(helpers, start=1):
                    cols.remove(h)
                    cols.insert(fk_ix + k, h)
                    moved.add(h)
                colpos = rebuild_index()

            out[name] = df.loc[:, cols]
        return out
    return _step