from __future__ import annotations
import argparse
import warnings

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.pipeline.registry import build_steps_from_yaml
from spreadsheet_handling.pipeline.steps import make_bootstrap_meta_step


_PACK_DEFAULT_STEPS = [
    make_bootstrap_meta_step(
        profile_defaults={"auto_filter": True, "freeze_header": True},
    ),
]


def _args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(
        prog="sheets-pack",
        description="Deprecated legacy shim: JSON/CSV -> XLSX. Prefer sheets-run for maintained workflows.",
    )
    p.add_argument("input_dir", help="Directory with .json or .csv")
    p.add_argument("-o", "--output", required=True, help="Output .xlsx file")
    p.add_argument("--input-kind", default="json", choices=["json", "json_dir", "csv_dir"])
    p.add_argument("--config", default=None, help="Pipeline YAML (overrides defaults)")
    p.add_argument("--no-defaults", action="store_true", help="Suppress default pipeline")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    warnings.warn(
        "sheets-pack is deprecated; prefer sheets-run or treat this command as a legacy example shim.",
        DeprecationWarning,
        stacklevel=2,
    )
    a = _args(argv)

    if a.config:
        steps = build_steps_from_yaml(a.config)
    elif a.no_defaults:
        steps = None
    else:
        steps = _PACK_DEFAULT_STEPS

    orchestrate(
        input={"kind": a.input_kind, "path": a.input_dir},
        output={"kind": "xlsx", "path": a.output},
        steps=steps,
    )
    print(f"[pack] XLSX geschrieben: {a.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
