"""Freshness guard for the domain-contracts staging -> canonical promote.

The export/import/promote loop is only safe when the staging snapshot was
produced from the *current* canonical state (Review 005, FIN-REVIEW-005-P1-2).
``make domain-contracts-export`` stamps the ODS workbook with a fingerprint of
the canonical registry; ``make domain-contracts-import`` carries that stamp
into staging; ``make domain-contracts-promote`` refuses to copy staging over
canonical unless the stamp still matches canonical.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANONICAL_DIR = ROOT / "registries" / "domain_contracts" / "canonical"

STAMP_FORMAT = 1


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


def write_stamp(canonical_dir: Path | str, stamp_path: Path | str) -> Path:
    stamp = Path(stamp_path)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stamp_format": STAMP_FORMAT,
        "canonical_fingerprint": canonical_fingerprint(canonical_dir),
    }
    stamp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return stamp


def verify_stamp(canonical_dir: Path | str, stamp_path: Path | str) -> tuple[bool, str]:
    """Return (ok, message) for a staging/export stamp against canonical."""
    stamp = Path(stamp_path)
    if not stamp.exists():
        return False, (
            f"Missing export stamp {stamp}. Staging was not produced by "
            "'make domain-contracts-export' + 'make domain-contracts-import' "
            "from the current canonical state; refusing to promote."
        )
    try:
        payload = json.loads(stamp.read_text(encoding="utf-8"))
        stamped = payload["canonical_fingerprint"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return False, f"Unreadable export stamp {stamp}; refusing to promote."
    current = canonical_fingerprint(canonical_dir)
    if stamped != current:
        return False, (
            "Stale staging: canonical changed since this staging snapshot was "
            "exported. Re-run 'make domain-contracts-export' / edit / "
            "'make domain-contracts-import' before promoting."
        )
    return True, "Staging export stamp matches current canonical state."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    stamp_parser = subparsers.add_parser("stamp", help="Write a canonical fingerprint stamp.")
    stamp_parser.add_argument("--canonical-dir", type=Path, default=DEFAULT_CANONICAL_DIR)
    stamp_parser.add_argument("--out", type=Path, required=True)

    verify_parser = subparsers.add_parser("verify", help="Verify a stamp against canonical.")
    verify_parser.add_argument("--canonical-dir", type=Path, default=DEFAULT_CANONICAL_DIR)
    verify_parser.add_argument("--stamp", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "stamp":
        print(write_stamp(args.canonical_dir, args.out))
        return 0
    ok, message = verify_stamp(args.canonical_dir, args.stamp)
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
