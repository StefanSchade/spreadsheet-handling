from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional

import pandas as pd

from ...core.fk import FK_PATTERN
from ...frame_keys import copy_reserved_frames, iter_data_frames

Frames = Dict[str, pd.DataFrame]
Step = Callable[[Frames], Frames]


@dataclass(frozen=True)
class MarkHelpersConfig:
    sheet: Optional[str]
    cols: Iterable[str]
    prefix: str = "_"


def mark_helpers(sheet: Optional[str], cols: Iterable[str], prefix: str = "_") -> Step:
    """
    Mark specified columns as helpers by renaming them with a prefix.
    - sheet=None -> apply on all sheets where the columns exist
    - no side effects on other sheets
    """
    cfg = MarkHelpersConfig(sheet=sheet, cols=tuple(cols), prefix=prefix)

    def _step(frames: Frames) -> Frames:
        out: dict[str, object] = {}
        copy_reserved_frames(frames, out)
        for name, df in iter_data_frames(frames):
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
        return out  # type: ignore[return-value]

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
    Remove auxiliary columns based on prefixes (fallback strategy).
    Metadata-based roles can be integrated later; the signature is already ready.
    """
    cfg = CleanAuxColumnsConfig(
        sheet=sheet,
        drop_roles=tuple(drop_roles),
        drop_prefixes=tuple(drop_prefixes),
    )

    def _step(frames: Frames) -> Frames:
        def _is_aux(col: object) -> bool:
            col_s = _first_nonempty_label(col)
            return any(col_s.startswith(p) for p in cfg.drop_prefixes)

        out: dict[str, object] = {}
        copy_reserved_frames(frames, out)
        for name, df in iter_data_frames(frames):
            if cfg.sheet is not None and name != cfg.sheet:
                out[name] = df
                continue
            if df.empty or df.columns.empty:
                out[name] = df
                continue

            keep = [c for c in df.columns if not _is_aux(c)]
            out[name] = df.loc[:, keep]
        return out  # type: ignore[return-value]

    return _step


def _flatten_header_to_level0(df: pd.DataFrame) -> pd.DataFrame:
    cols_in = list(df.columns)
    cols_out = [(c[0] if isinstance(c, tuple) and len(c) else c) for c in cols_in]
    if cols_in == cols_out:
        return df
    out = df.copy()
    out.columns = cols_out
    return out


def flatten_headers(
    sheet: Optional[str] = None,
    *,
    mode: str = "first_nonempty",
    sep: str = "",
) -> Step:
    def _step(frames: Frames) -> Frames:
        out: dict[str, object] = {}
        copy_reserved_frames(frames, out)
        for name, df in iter_data_frames(frames):
            if sheet is not None and name != sheet:
                out[name] = df
                continue
            cols = list(df.columns)
            has_tuples = any(isinstance(c, tuple) for c in cols)
            if not isinstance(df.columns, pd.MultiIndex) and not has_tuples:
                out[name] = df
                continue

            tuples = [tuple(c) if isinstance(c, tuple) else (str(c),) for c in cols]
            if mode == "level0":
                new = [str(t[0]) for t in tuples]
            elif mode == "join":
                new = [sep.join(str(x) for x in t) for t in tuples]
            else:
                new = [next((str(x) for x in t if str(x)), "") for t in tuples]

            nd = df.copy()
            nd.columns = new
            out[name] = nd
        return out  # type: ignore[return-value]

    return _step


def unflatten_headers(sheet: Optional[str] = None, *, sep: str = ".") -> Step:
    """
    Convert flat string headers into a MultiIndex by splitting with `sep`.

    Notes
    -----
    - If a frame already has MultiIndex columns, it is passed through unchanged.
    - Reversibility is guaranteed only when headers were flattened with a stable
      separator and no header part contains that separator.
    """

    def _step(frames: Frames) -> Frames:
        if not sep:
            raise ValueError("unflatten_headers requires a non-empty sep")

        out: dict[str, object] = {}
        copy_reserved_frames(frames, out)
        for name, df in iter_data_frames(frames):
            if sheet is not None and name != sheet:
                out[name] = df
                continue

            if isinstance(df.columns, pd.MultiIndex):
                out[name] = df
                continue

            cols = [str(c) for c in list(df.columns)]
            parts = [c.split(sep) for c in cols]
            max_levels = max((len(p) for p in parts), default=1)
            tuples = [tuple(p + [""] * (max_levels - len(p))) for p in parts]

            nd = df.copy()
            nd.columns = pd.MultiIndex.from_tuples(tuples)
            out[name] = nd
        return out  # type: ignore[return-value]

    return _step


def _first_nonempty_label(col: object) -> str:
    """
    Return the visible label of a column:
    - for MultiIndex/tuple columns: first non-empty level
    - otherwise: str(col)
    """
    if isinstance(col, tuple):
        for x in col:
            s = str(x)
            if s:
                return s
        return ""
    return str(col)


def reorder_helpers_next_to_fk(
    sheet: Optional[str] = None,
    *,
    helper_prefix: str = "_",
) -> Step:
    """
    Move helper columns so they sit immediately behind their FK column.

    Heuristic:
    - FK is named id_(<target>) or another FK_PATTERN-compatible header
    - matching helpers start with f"{helper_prefix}{<target>}_"

    Works for both flat and tuple/MultiIndex-like columns.
    """

    def _step(frames: Frames) -> Frames:
        out: dict[str, object] = {}
        copy_reserved_frames(frames, out)
        for name, df in iter_data_frames(frames):
            if sheet is not None and name != sheet:
                out[name] = df
                continue
            if df.empty:
                out[name] = df
                continue

            cols = list(df.columns)
            labels: Dict[object, str] = {c: _first_nonempty_label(c) for c in cols}

            def rebuild_index() -> Dict[object, int]:
                return {c: i for i, c in enumerate(cols)}

            colpos = rebuild_index()
            moved: set[object] = set()

            for c in list(cols):
                label = labels[c]
                m = FK_PATTERN.match(label)
                if not m:
                    continue

                target = m.group("sheet_key")
                helpers = [
                    h
                    for h in cols
                    if h not in moved
                    and labels.get(h, "").startswith(f"{helper_prefix}{target}_")
                ]
                if not helpers:
                    continue

                # Remove the whole helper group first, then recompute the FK index.
                # This keeps the placement correct even when helpers were already left
                # of the FK before reordering.
                for h in helpers:
                    cols.remove(h)

                colpos = rebuild_index()
                fk_ix = colpos.get(c, -1)
                if fk_ix < 0:
                    continue

                for k, h in enumerate(helpers, start=1):
                    cols.insert(fk_ix + k, h)
                    moved.add(h)
                colpos = rebuild_index()

            out[name] = df.loc[:, cols]
        return out  # type: ignore[return-value]

    return _step
