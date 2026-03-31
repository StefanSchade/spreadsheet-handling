from __future__ import annotations

from typing import Any, Mapping
import json
import os
from pathlib import Path
from typing import Dict

import pandas as pd
import yaml

from .base import BackendBase, BackendOptions, coerce_backend_options

Frames = Dict[str, pd.DataFrame]


def _is_empty_header_segment(x: Any) -> bool:
    if x is None:
        return True
    s = str(x).strip()
    return s == "" or s.lower() in ("nan", "none") or s.startswith("Unnamed:")


def _set_nested(d: dict[str, Any], segs: list[str], value: Any) -> None:
    cur = d
    for i, s in enumerate(segs):
        last = i == len(segs) - 1
        if last:
            cur[s] = value
        else:
            nxt = cur.get(s)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[s] = nxt
            cur = nxt


def _records_nested_from_multiindex(df: pd.DataFrame) -> list[dict[str, Any]]:
    paths: list[list[str] | None] = []
    for col in df.columns:
        if isinstance(col, tuple):
            segs = [str(s) for s in col if not _is_empty_header_segment(s)]
        else:
            segs = [str(col)] if not _is_empty_header_segment(col) else []
        if not segs or segs[0].startswith("_"):
            paths.append(None)
        else:
            paths.append(segs)

    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        obj: dict[str, Any] = {}
        for idx, segs in enumerate(paths):
            if segs is None:
                continue
            v = row.iloc[idx]
            if v is None:
                continue
            if isinstance(v, str) and v.strip() == "":
                continue
            _set_nested(obj, segs, v)
        out.append(obj)
    return out


class JSONBackend(BackendBase):
    """
    Backend for a directory of JSON files, one file per sheet (e.g. products.json).
    """

    def read_multi(self, path: str, header_levels: int, options: BackendOptions | None = None) -> Frames:
        if isinstance(path, dict):
            raise TypeError(
                "input.path must be a string/Path, not a dict. "
                "Did you accidentally put writer options under 'path:' in your YAML? "
                "Use 'input: { kind: json_dir, path: ./in, options: {...} }'."
            )
        in_dir = Path(path)
        out: Frames = {}
        for p in sorted(in_dir.glob("*.json")):
            df = pd.read_json(p, dtype=str)
            df = df.where(pd.notnull(df), "")  # normalize empties as ""
            out[p.stem] = df

        # --- read optional _meta sidecar ------------------------------------
        sidecar = in_dir / "_meta.yaml"
        if sidecar.exists():
            with open(sidecar, encoding="utf-8") as fh:
                meta = yaml.safe_load(fh)
            if isinstance(meta, dict):
                out["_meta"] = meta  # type: ignore[assignment]

        return out

    def write_multi(self, frames: Frames, path: str, options: BackendOptions | None = None) -> None:

        if isinstance(path, dict):
            raise TypeError(
                "output.path must be a string/Path, not a dict. "
                "Did you accidentally put writer options under 'path:' in your YAML? "
                "Use 'output: { kind: json_dir, path: ./out, options: {...} }'."
            )
        out_dir = Path(os.fspath(path))

        out_dir.mkdir(parents=True, exist_ok=True)
        # --- formatting defaults (jq-like pretty print) ---
        fmt = {
                "pretty": True,
                "indent": 2,
                "sort_keys": False,     # bewahrt Spaltenreihenfolge aus dem DF
                "ensure_ascii": False,
        }
        if options:
            fmt.update({k: options[k] for k in ("pretty", "indent", "sort_keys", "ensure_ascii") if k in options})

        for name, df in frames.items():
            if name == "_meta":
                continue  # handled separately as sidecar below
            p = out_dir / f"{name}.json"
            # NaNs -> "", Reihenfolge = DataFrame-Spaltenreihenfolge
            clean = df.where(pd.notnull(df), "")
            if isinstance(clean.columns, pd.MultiIndex):
                # FTR-MULTIHEADER-P2 default: MultiIndex headers become nested JSON objects.
                records = _records_nested_from_multiindex(clean)
            else:
                records = clean.to_dict(orient="records")
            # Schreiben
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                if fmt["pretty"]:
                    json.dump(records, fh, ensure_ascii=fmt["ensure_ascii"],
                              indent=fmt["indent"],
                              sort_keys=fmt["sort_keys"])
                    fh.write("\n")  # schöner Abschluss für Git
                else:
                    json.dump(records, fh, ensure_ascii=fmt["ensure_ascii"],
                              separators=(",", ":"),  # kompakt
                              sort_keys=fmt["sort_keys"])
                    fh.write("\n")

        # --- write optional _meta sidecar -----------------------------------
        meta = frames.get("_meta")
        if meta is not None and isinstance(meta, dict):
            sidecar = out_dir / "_meta.yaml"
            with open(sidecar, "w", encoding="utf-8", newline="\n") as fh:
                yaml.safe_dump(meta, fh, default_flow_style=False, allow_unicode=True)

# ---- Test-facing convenience wrappers (kept for compatibility) ----

def read_json_dir(path: str, *, header_levels: int = 1, options: Mapping[str, Any] | BackendOptions | None = None) -> dict[str, pd.DataFrame]:
    """
    Public convenience wrapper used by get_loader(). Accepts optional options.
    """
    from .json_backend import JSONBackend  # keep local to avoid circulars
    return JSONBackend().read_multi(path, header_levels=header_levels, options=coerce_backend_options(options))


def write_json_dir(
    frames: Frames,
    path: str | os.PathLike[str],
    *,
    options: Mapping[str, Any] | BackendOptions | None = None,
) -> None:
    """
    Write frames to a directory of JSON files, one per sheet.
    """
    JSONBackend().write_multi(frames, os.fspath(path), options=coerce_backend_options(options))
