from __future__ import annotations

import argparse

from spreadsheet_handling.application.orchestrator import orchestrate


def _args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sheets-example-xlsx-to-json",
        description=(
            "Reference shortcut command: write an XLSX workbook to a JSON "
            "directory using the supported wrapper pattern."
        ),
    )
    parser.add_argument("workbook", help="Input .xlsx file")
    parser.add_argument("-o", "--output-dir", required=True, help="Output directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    orchestrate(
        input={"kind": "xlsx", "path": args.workbook},
        output={"kind": "json_dir", "path": args.output_dir},
    )
    print(f"[example-xlsx-to-json] Wrote JSON directory: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
