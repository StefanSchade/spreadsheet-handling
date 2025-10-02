from __future__ import annotations
import argparse, sys, yaml
from pathlib import Path
from ..pipeline.config import AppConfig, IOConfig, IOEndpoint, PipelineConfig, ExcelOptions
from ..pipeline.runner import run_pipeline

def _args():
    p = argparse.ArgumentParser(prog="sheets-pack", description="JSON/CSV -> XLSX")
    p.add_argument("input_dir", help="Directory with .json or .csv")
    p.add_argument("-o", "--output", required=True, help="Output .xlsx file")
    p.add_argument("--input-kind", default="json", choices=["json","json_dir","csv_dir"])
    return p.parse_args()

def main(argv: list[str] | None = None) -> int:
    a = _args()
    app = AppConfig(
        io=IOConfig(
            inputs={"primary": IOEndpoint(kind=a.input_kind, path=a.input_dir)},
            output=IOEndpoint(kind="xlsx", path=a.output),
        ),
        pipeline=PipelineConfig(steps=[]),
        excel=ExcelOptions(),  # defaults: autofilter + gray header
        strict=False,
    )
    frames, meta, issues = run_pipeline(app)
    print(f"[pack] XLSX geschrieben: {a.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
