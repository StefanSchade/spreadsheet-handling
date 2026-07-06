"""Freshness and workbook-binding guard for the domain-contracts review loop.

The export/import/promote loop is only safe when (a) the staging snapshot was
produced from the *current* canonical state and (b) the workbook being
imported is the one the export actually wrote (Review 005,
FIN-REVIEW-005-P1-2 and follow-up Slice 1b).

``make domain-contracts-export`` stamps the ODS workbook with a fingerprint of
the canonical registry *and* a SHA-256 of the workbook bytes;
``make domain-contracts-import`` refuses a workbook that does not match its
stamp, then carries the stamp into staging; ``make domain-contracts-promote``
refuses to copy staging over canonical unless the stamp still matches
canonical.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANONICAL_DIR = ROOT / "registries" / "domain_contracts" / "canonical"

# Format 2 added workbook_sha256 (Slice 1b). Older stamps are refused so a
# pre-binding workbook cannot be imported against a format-1 sidecar.
STAMP_FORMAT = 2


def canonical_fingerprint(canonical_dir: Path | str) -> str:
    """Return a stable fingerprint of the top-level canonical table files."""
    canonical = Path(canonical_dir)
    digest = hashlib.sha256()
    for path in sorted(canonical.glob("*.json")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def workbook_sha256(workbook_path: Path | str) -> str:
    return hashlib.sha256(Path(workbook_path).read_bytes()).hexdigest()


def write_stamp(
    canonical_dir: Path | str,
    stamp_path: Path | str,
    workbook_path: Path | str,
) -> Path:
    stamp = Path(stamp_path)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stamp_format": STAMP_FORMAT,
        "canonical_fingerprint": canonical_fingerprint(canonical_dir),
        "workbook_sha256": workbook_sha256(workbook_path),
    }
    stamp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return stamp


def _load_stamp(stamp_path: Path) -> tuple[dict | None, str]:
    """Return (payload, error_message); payload is None when unusable."""
    if not stamp_path.exists():
        return None, (
            f"Missing export stamp {stamp_path}. Re-run 'make domain-contracts-export' "
            "so the workbook and staging carry a current stamp."
        )
    try:
        payload = json.loads(stamp_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("stamp payload must be an object")
    except (json.JSONDecodeError, TypeError):
        return None, f"Unreadable export stamp {stamp_path}; re-run 'make domain-contracts-export'."
    if payload.get("stamp_format") != STAMP_FORMAT:
        return None, (
            f"Export stamp {stamp_path} has format {payload.get('stamp_format')!r}, "
            f"expected {STAMP_FORMAT}. Re-run 'make domain-contracts-export' to produce "
            "a current stamp."
        )
    return payload, ""


def verify_stamp(canonical_dir: Path | str, stamp_path: Path | str) -> tuple[bool, str]:
    """Return (ok, message) for a staging/export stamp against canonical."""
    payload, error = _load_stamp(Path(stamp_path))
    if payload is None:
        return False, error
    if payload.get("canonical_fingerprint") != canonical_fingerprint(canonical_dir):
        return False, (
            "Stale staging: canonical changed since this staging snapshot was "
            "exported. Re-run 'make domain-contracts-export' / edit / "
            "'make domain-contracts-import' before promoting."
        )
    return True, "Staging export stamp matches current canonical state."


EMBEDDED_MARKER_KEY = "domain_contracts_export"


def embedded_workbook_fingerprint(workbook_path: Path | str) -> str | None:
    """Read the canonical fingerprint the export embedded into workbook _meta.

    Imported lazily because parsing the ODS needs the spreadsheet backend;
    the promote-time ``verify`` path must stay import-light.
    """
    from spreadsheet_handling.io_backends.ods.ods_backend import OdsBackend

    frames = OdsBackend().read_multi(str(workbook_path), header_levels=1)
    meta = frames.get("_meta")
    if not isinstance(meta, dict):
        return None
    marker = meta.get(EMBEDDED_MARKER_KEY)
    if not isinstance(marker, dict):
        return None
    value = marker.get("canonical_fingerprint")
    return value if isinstance(value, str) else None


def verify_workbook(stamp_path: Path | str, workbook_path: Path | str) -> tuple[bool, str]:
    """Return (ok, message) binding the stamp to the workbook being imported.

    Two accepted proofs:

    * byte identity - the workbook is exactly the file the export wrote
      (``workbook_sha256``); or
    * embedded fingerprint - the workbook was edited (LibreOffice rewrites
      the bytes on save), but its ``_meta`` still carries the canonical
      fingerprint the export embedded, proving descent from the stamped
      export generation.

    A workbook matching neither (stale copy, foreign file, stripped meta)
    is refused.
    """
    payload, error = _load_stamp(Path(stamp_path))
    if payload is None:
        return False, error
    workbook = Path(workbook_path)
    if not workbook.exists():
        return False, f"Missing workbook {workbook}; run 'make domain-contracts-export' first."
    if payload.get("workbook_sha256") == workbook_sha256(workbook):
        return True, "Workbook bytes match the export stamp."
    embedded = embedded_workbook_fingerprint(workbook)
    if embedded is None:
        return False, (
            f"Workbook {workbook.name} does not match its export stamp and carries no "
            "embedded export fingerprint. It is not the stamped export (or its edited "
            "descendant); re-run 'make domain-contracts-export' before importing."
        )
    if embedded != payload.get("canonical_fingerprint"):
        return False, (
            f"Workbook {workbook.name} was exported from a different canonical state "
            "than the current stamp (stale or mixed-in workbook). Refusing to import; "
            "re-run 'make domain-contracts-export' and redo the edits on the fresh export."
        )
    return True, "Edited workbook descends from the stamped export (embedded fingerprint match)."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    stamp_parser = subparsers.add_parser("stamp", help="Write a canonical+workbook stamp.")
    stamp_parser.add_argument("--canonical-dir", type=Path, default=DEFAULT_CANONICAL_DIR)
    stamp_parser.add_argument("--workbook", type=Path, required=True)
    stamp_parser.add_argument("--out", type=Path, required=True)

    verify_parser = subparsers.add_parser("verify", help="Verify a stamp against canonical.")
    verify_parser.add_argument("--canonical-dir", type=Path, default=DEFAULT_CANONICAL_DIR)
    verify_parser.add_argument("--stamp", type=Path, required=True)

    workbook_parser = subparsers.add_parser(
        "verify-workbook", help="Verify a workbook against its export stamp."
    )
    workbook_parser.add_argument("--stamp", type=Path, required=True)
    workbook_parser.add_argument("--workbook", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "stamp":
        print(write_stamp(args.canonical_dir, args.out, args.workbook))
        return 0
    if args.command == "verify":
        ok, message = verify_stamp(args.canonical_dir, args.stamp)
    else:
        ok, message = verify_workbook(args.stamp, args.workbook)
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
