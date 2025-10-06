from __future__ import annotations

from typing import Any, Mapping, cast
import json

try:
    # wherever BackendOptions lives in your tree
    from ..pipeline.types import BackendOptions
except Exception:
    # fallback to keep things running even if the import changes again
    BackendOptions = dict[str, Any]  # type: ignore[assignment]

from dataclasses import is_dataclass
import os
from pathlib import Path
from typing import Dict

import pandas as pd

from .base import BackendBase, BackendOptions

Frames = Dict[str, pd.DataFrame]


def _coerce_options(opts: Mapping[str, Any] | BackendOptions | None) -> BackendOptions:
    """
    Accept None | dict | BackendOptions and return BackendOptions.
    - If BackendOptions is a dataclass type, construct it from the mapping.
    - Otherwise (TypedDict / alias), return a plain dict casted to BackendOptions.
    """
    if opts is None:
        # empty default
        return cast(BackendOptions, {})
    # if the "type" itself is a class / dataclass constructor, try to build it
    try:
        # hasattr check avoids calling is_dataclass on non-class aliases
        if isinstance(BackendOptions, type) and is_dataclass(BackendOptions):
            return BackendOptions(**dict(opts))  # type: ignore[misc,call-arg]
    except Exception:
        pass
    # Otherwise just return a plain dict (compatible with TypedDict/alias)
    return cast(BackendOptions, dict(opts))

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
            p = out_dir / f"{name}.json"
            # NaNs -> "", Reihenfolge = DataFrame-Spaltenreihenfolge
            clean = df.where(pd.notnull(df), "")
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

# ---- Test-facing convenience wrappers (kept for compatibility) ----

def read_json_dir(path: str, *, header_levels: int = 1, options: Mapping[str, Any] | BackendOptions | None = None) -> dict[str, pd.DataFrame]:
    """
    Public convenience wrapper used by get_loader(). Accepts optional options.
    """
    from .json_backend import JSONBackend  # keep local to avoid circulars
    return JSONBackend().read_multi(path, header_levels=header_levels, options=_coerce_options(options))


def write_json_dir(arg1, arg2=None, *, options: Mapping[str, Any] | BackendOptions | None = None) -> None:
    """
    Backward- & forward-compatible:
      - write_json_dir(path, frames)
      - write_json_dir(frames, path)
    """
    from .json_backend import JSONBackend

    def _is_pathlike(x):
        from pathlib import Path
        import os as _os
        return isinstance(x, (str, Path)) or hasattr(x, "__fspath__") or isinstance(x, _os.PathLike)

    if _is_pathlike(arg1) and isinstance(arg2, dict):
        path = arg1
        frames = arg2
    elif isinstance(arg1, dict) and _is_pathlike(arg2):
        frames = arg1
        path = arg2
    else:
        raise TypeError("write_json_dir expects (path, frames) or (frames, path)")

    JSONBackend().write_multi(frames, path, options=_coerce_options(options))