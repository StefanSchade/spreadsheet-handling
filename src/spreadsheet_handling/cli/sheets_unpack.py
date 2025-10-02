from __future__ import annotations
import argparse
from pathlib import Path
from ..pipeline.config import AppConfig, IOConfig, IOEndpoint, PipelineConfig, ExcelOptions
from ..pipeline.runner import run_pipeline

def _args():
    p = argparse.ArgumentParser(prog="sheets-unpack", description="XLSX -> JSON")
    p.add_argument("workbook", help="Input .xlsx file")
    p.add_argument("-o", "--output-dir", required=True, help="Output directory")
    return p.parse_args()

def main(argv: list[str] | None = None) -> int:
    a = _args()
    app = AppConfig(
        io=IOConfig(
            inputs={"primary": IOEndpoint(kind="xlsx", path=a.workbook)},
            output=IOEndpoint(kind="json_dir", path=a.output_dir),
        ),
        pipeline=PipelineConfig(steps=[]),
        excel=ExcelOptions(),
        strict=False,
    )
    frames, meta, issues = run_pipeline(app)
    print(f"[unpack] JSONs geschrieben nach: {a.output_dir}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
