from __future__ import annotations
import argparse
import warnings

from spreadsheet_handling.application.orchestrator import orchestrate


def _args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(
        prog="sheets-unpack",
        description="Deprecated legacy shim: XLSX -> JSON. Prefer sheets-run for maintained workflows.",
    )
    p.add_argument("workbook", help="Input .xlsx file")
    p.add_argument("-o", "--output-dir", required=True, help="Output directory")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    warnings.warn(
        "sheets-unpack is deprecated; prefer sheets-run or treat this command as a legacy example shim.",
        DeprecationWarning,
        stacklevel=2,
    )
    a = _args(argv)
    orchestrate(
        input={"kind": "xlsx", "path": a.workbook},
        output={"kind": "json_dir", "path": a.output_dir},
    )
    print(f"[unpack] JSONs geschrieben nach: {a.output_dir}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
