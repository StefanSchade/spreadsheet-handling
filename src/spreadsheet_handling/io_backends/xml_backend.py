from __future__ import annotations

from typing import Any, Dict, Mapping, cast
from dataclasses import is_dataclass
from pathlib import Path
import os

import pandas as pd
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent
import xml.etree.ElementTree as ET

from .base import BackendBase, BackendOptions

Frames = Dict[str, pd.DataFrame]


def _is_empty_header_segment(x: Any) -> bool:
    if x is None:
        return True
    s = str(x).strip()
    return s == "" or s.lower() in ("nan", "none") or s.startswith("Unnamed:")


def _coerce_options(opts: Mapping[str, Any] | BackendOptions | None) -> BackendOptions:
    if opts is None:
        return cast(BackendOptions, {})
    try:
        if isinstance(BackendOptions, type) and is_dataclass(BackendOptions):
            return BackendOptions(**dict(opts))  # type: ignore[misc,call-arg]
    except Exception:
        pass
    return cast(BackendOptions, dict(opts))


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def _sanitize_tag(name: str) -> str:
    """Make a string safe for use as an XML element name."""
    tag = name.replace(" ", "_").replace("/", "_").replace(".", "_")
    if not tag or not (tag[0].isalpha() or tag[0] == "_"):
        tag = "_" + tag
    return tag


def _row_to_nested_xml(parent: Element, col_paths: list[list[str] | None], row: pd.Series) -> None:
    """Build nested XML elements from a single row using MultiIndex column paths."""
    # Track sub-elements by first segment so siblings share a parent
    subs: dict[str, Element] = {}
    for idx, segs in enumerate(col_paths):
        if segs is None:
            continue
        v = row.iloc[idx]
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue

        # Walk down the segment path creating sub-elements
        cur = parent
        key_trail = ""
        for i, seg in enumerate(segs):
            tag = _sanitize_tag(seg)
            last = i == len(segs) - 1
            key_trail += "/" + tag
            if last:
                el = SubElement(cur, tag)
                el.text = str(v)
            else:
                if key_trail not in subs:
                    el = SubElement(cur, tag)
                    subs[key_trail] = el
                cur = subs[key_trail]


def _row_to_flat_xml(parent: Element, columns: list[str], row: pd.Series) -> None:
    """Build flat XML elements from a single row."""
    for col_name, value in zip(columns, row):
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        el = SubElement(parent, _sanitize_tag(str(col_name)))
        el.text = str(value)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def _xml_element_to_records(root: Element) -> list[dict[str, Any]]:
    """
    Parse XML of the form:
        <sheet>
          <row> ... </row>
          ...
        </sheet>
    Each <row> may contain nested sub-elements which become dotted keys.
    """
    records: list[dict[str, Any]] = []
    for row_el in root:
        rec: dict[str, Any] = {}
        _flatten_element(row_el, [], rec)
        records.append(rec)
    return records


def _flatten_element(el: Element, prefix: list[str], rec: dict[str, Any]) -> None:
    """Recursively flatten nested XML elements into dotted-key dict entries."""
    children = list(el)
    if not children:
        # Leaf node
        key = ".".join(prefix) if prefix else el.tag
        rec[key] = el.text or ""
    else:
        for child in children:
            _flatten_element(child, prefix + [child.tag], rec)


# ---------------------------------------------------------------------------
# Backend class
# ---------------------------------------------------------------------------

class XMLBackend(BackendBase):
    """
    Backend for a directory of XML files, one file per sheet.

    Write behaviour:
    - MultiIndex columns produce nested XML elements.
    - Flat columns produce flat child elements under each <row>.

    Read behaviour:
    - Nested XML is flattened to dotted column names (e.g. "order.id").
    - Use unflatten_headers edge step to rebuild MultiIndex if needed.
    """

    def read_multi(self, path: str, header_levels: int, options: BackendOptions | None = None) -> Frames:
        if isinstance(path, dict):
            raise TypeError(
                "input.path must be a string/Path, not a dict."
            )
        in_dir = Path(path)
        out: Frames = {}
        for p in sorted(in_dir.glob("*.xml")):
            tree = ET.parse(p)  # noqa: S314 – trusted local files only
            root = tree.getroot()
            records = _xml_element_to_records(root)
            if records:
                df = pd.DataFrame(records).fillna("")
            else:
                df = pd.DataFrame()
            out[p.stem] = df
        return out

    def write_multi(self, frames: Frames, path: str, options: BackendOptions | None = None) -> None:
        if isinstance(path, dict):
            raise TypeError(
                "output.path must be a string/Path, not a dict."
            )
        out_dir = Path(os.fspath(path))
        out_dir.mkdir(parents=True, exist_ok=True)

        for name, df in frames.items():
            p = out_dir / f"{name}.xml"
            clean = df.where(pd.notnull(df), "")
            root = Element(_sanitize_tag(name))

            if isinstance(clean.columns, pd.MultiIndex):
                # Build column paths, skipping helper columns
                col_paths: list[list[str] | None] = []
                for col in clean.columns:
                    if isinstance(col, tuple):
                        segs = [str(s) for s in col if not _is_empty_header_segment(s)]
                    else:
                        segs = [str(col)] if not _is_empty_header_segment(col) else []
                    if not segs or segs[0].startswith("_"):
                        col_paths.append(None)
                    else:
                        col_paths.append(segs)

                for _, row in clean.iterrows():
                    row_el = SubElement(root, "row")
                    _row_to_nested_xml(row_el, col_paths, row)
            else:
                columns = [str(c) for c in clean.columns if not str(c).startswith("_")]
                for _, row in clean.iterrows():
                    row_el = SubElement(root, "row")
                    _row_to_flat_xml(row_el, columns, row)

            indent(root, space="  ")
            tree = ElementTree(root)
            with open(p, "wb") as fh:
                tree.write(fh, encoding="utf-8", xml_declaration=True)
            # Ensure trailing newline for git
            with open(p, "a", encoding="utf-8", newline="\n") as fh:
                fh.write("\n")


# ---------------------------------------------------------------------------
# Convenience wrappers (for router.py)
# ---------------------------------------------------------------------------

def read_xml_dir(path: str, *, header_levels: int = 1,
                 options: Mapping[str, Any] | BackendOptions | None = None) -> Frames:
    return XMLBackend().read_multi(path, header_levels=header_levels, options=_coerce_options(options))


def write_xml_dir(frames: Frames, path: str, *,
                  options: Mapping[str, Any] | BackendOptions | None = None) -> None:
    """Write frames to a directory of XML files, one per sheet."""
    XMLBackend().write_multi(frames, str(path), options=_coerce_options(options))
