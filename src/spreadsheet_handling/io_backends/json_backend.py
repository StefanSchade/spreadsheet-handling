from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import datetime
import json
import os
from pathlib import Path
from typing import Dict

import pandas as pd
import yaml

from .base import BackendBase, BackendOptions, coerce_backend_options

Frames = Dict[str, pd.DataFrame]

_JSON_FORMAT_KEYS = ("pretty", "indent", "sort_keys", "ensure_ascii")


def _json_temporal_default(value: Any) -> Any:
    """Persistence-local temporal encoder for `json.dump(..., default=...)`.

    Ordered checks -- `pandas.NaT` before `pandas.Timestamp` before plain
    `datetime.datetime` before `datetime.date` -- per the accepted D-T2.2
    contract (`FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A` section 27.9):

    * `value is pd.NaT` (temporal Missing) -> `""`, matching every other
      column's existing Missing convention (this module's own
      `df.where(pd.notnull(df), "")` write-side normalization). Checked
      first because `pandas.NaTType` subclasses both `datetime.datetime` and
      `datetime.date` -- without this leading check `pd.NaT` would silently
      encode as `{"$datetime": "NaT"}` instead.
    * `isinstance(value, pd.Timestamp)` -> `{"$datetime":
      value.as_unit("us").isoformat()}` -- truncated to microsecond
      precision before `.isoformat()`, since `pandas.Timestamp.isoformat()`
      emits up to nine fractional-second digits for a nanosecond-precision
      value, unlike `datetime.datetime.isoformat()`'s maximum of six.
    * `isinstance(value, datetime.datetime)` -> `{"$datetime":
      value.isoformat()}` (offset suffix present iff timezone-aware, absent
      iff naive; no truncation needed, a plain `datetime.datetime` carries no
      sub-microsecond component).
    * `isinstance(value, datetime.date)` -> `{"$date": value.isoformat()}`.
    * anything else -> `raise TypeError`, reproducing exactly the `TypeError`
      `json.dumps` already raises for an unsupported type with no `default=`
      callback at all -- no bare fallback that could accidentally widen
      acceptance.

    Private, unexported, and scoped to exactly `JSONBackend.write_multi`'s
    own `json.dump` calls -- not a general normalization primitive
    (`normalize_scalar()`-shaped or otherwise) and not part of Trusted
    Ingress.
    """
    if value is pd.NaT:
        return ""
    if isinstance(value, pd.Timestamp):
        return {"$datetime": value.as_unit("us").isoformat()}
    if isinstance(value, datetime.datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, datetime.date):
        return {"$date": value.isoformat()}
    raise TypeError(
        f"Object of type {type(value).__name__!r} is not JSON serializable"
    )


def _json_temporal_object_hook(obj: dict[str, Any]) -> Any:
    """Persistence-local temporal decoder for `json.loads(..., object_hook=...)`.

    Symmetric counterpart to `_json_temporal_default` (D-T2.3, accepted
    contract section 27.12's "Decode rules"). Recognizes only exact
    reserved single-key envelopes:

    * `{"$date": "<str>"}` -> `datetime.date.fromisoformat(<str>)`.
    * `{"$datetime": "<str>"}` -> `datetime.datetime.fromisoformat(<str>)`.

    A matched envelope whose value is not a string, or is a string that
    fails the corresponding `fromisoformat` parse, raises `ValueError` --
    it must not silently pass through as an ordinary dict once the reserved
    key shape has matched. Any dict that does not match either reserved key
    set exactly (extra keys, wrong key name) passes through unchanged, so an
    ordinary nested (e.g. MultiIndex-payload) object is never misclassified.

    Private, unexported, tested directly as a standalone codec -- this is a
    persistence codec component, not wired into `JSONBackend.read_multi`/
    `read_json_dir` (Option B, accepted contract section 27.11).
    """
    if set(obj.keys()) == {"$date"}:
        raw = obj["$date"]
        if not isinstance(raw, str):
            raise ValueError(
                "malformed $date envelope: expected a string value, got "
                f"{type(raw).__name__!r}"
            )
        return datetime.date.fromisoformat(raw)
    if set(obj.keys()) == {"$datetime"}:
        raw = obj["$datetime"]
        if not isinstance(raw, str):
            raise ValueError(
                "malformed $datetime envelope: expected a string value, got "
                f"{type(raw).__name__!r}"
            )
        return datetime.datetime.fromisoformat(raw)
    return obj


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


def _json_format_overrides(options: BackendOptions | Mapping[str, Any] | None) -> dict[str, Any]:
    if options is None:
        return {}
    if isinstance(options, BackendOptions):
        return {key: options.extra[key] for key in _JSON_FORMAT_KEYS if key in options.extra}
    return {key: options[key] for key in _JSON_FORMAT_KEYS if key in options}


class JSONBackend(BackendBase):
    """
    Backend for a directory of JSON files, one file per sheet (e.g. products.json).

    Temporal wire format (D-T2.2, accepted contract
    `FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A` section 27.5): `$date` and
    `$datetime` are *reserved* single-key object envelopes on write --
    `{"$date": "<datetime.date.isoformat() string>"}` for a Date value,
    `{"$datetime": "<datetime.datetime.isoformat() string>"}` (offset suffix
    present iff timezone-aware, absent iff naive) for a DateTime value, at
    most microsecond precision. A missing temporal cell (`pandas.NaT`)
    writes as `""`, matching every other column's existing Missing
    convention -- never `{"$datetime": "NaT"}`. Named/IANA timezone identity
    is not preserved by this wire format (only the numeric UTC offset is);
    carrier identity (`pandas.Timestamp` vs plain `datetime.datetime`) is
    not preserved either. A legitimate data column whose only field is
    literally named `$date` or `$datetime` would collide with this envelope
    shape; no repository evidence shows a column named this today.

    `write_multi` (via `write_json_dir`) emits this format for
    `datetime.date`/`datetime.datetime`/`pandas.Timestamp` cell values.
    `read_multi` (via `read_json_dir`) is deliberately, and for this slice
    permanently, *not* wired to decode it (Option B, accepted contract
    section 27.11) -- reading a file containing a `$date`/`$datetime`
    envelope back through this backend's own `dtype=str` read contract
    produces a stringified, unparseable Python-repr value, not a native
    `datetime.date`/`datetime.datetime`. A private, symmetric decoder
    (`_json_temporal_object_hook`) exists and is exercised directly as a
    standalone codec by the test suite; it is not called from `read_multi`.
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
            df = pd.read_json(p, dtype=str, convert_dates=False)
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
                "sort_keys": False,     # preserve DataFrame column order
                "ensure_ascii": False,
        }
        fmt.update(_json_format_overrides(options))

        for name, df in frames.items():
            if name == "_meta":
                continue  # handled separately as sidecar below
            p = out_dir / f"{name}.json"
            # Normalize NaNs to ""; order follows the DataFrame columns.
            clean = df.where(pd.notnull(df), "")
            if isinstance(clean.columns, pd.MultiIndex):
                # FTR-MULTIHEADER-P2 default: MultiIndex headers become nested JSON objects.
                records = _records_nested_from_multiindex(clean)
            else:
                records = clean.to_dict(orient="records")
            # Write records.
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                if fmt["pretty"]:
                    json.dump(records, fh, ensure_ascii=fmt["ensure_ascii"],
                              indent=fmt["indent"],
                              sort_keys=fmt["sort_keys"],
                              default=_json_temporal_default)
                    fh.write("\n")  # keep Git diffs tidy
                else:
                    json.dump(records, fh, ensure_ascii=fmt["ensure_ascii"],
                              separators=(",", ":"),  # compact
                              sort_keys=fmt["sort_keys"],
                              default=_json_temporal_default)
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
