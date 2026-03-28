from __future__ import annotations
import argparse

from spreadsheet_handling.orchestrator import orchestrate


def _args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="sheets-pack", description="JSON/CSV -> XLSX")
    p.add_argument("input_dir", help="Directory with .json or .csv")
    p.add_argument("-o", "--output", required=True, help="Output .xlsx file")
    p.add_argument("--input-kind", default="json", choices=["json", "json_dir", "csv_dir"])
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    a = _args(argv)
    orchestrate(
        input={"kind": a.input_kind, "path": a.input_dir},
        output={"kind": "xlsx", "path": a.output},
    )
    print(f"[pack] XLSX geschrieben: {a.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
