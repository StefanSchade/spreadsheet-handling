from __future__ import annotations

import argparse

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.pipeline import build_steps_from_yaml
from spreadsheet_handling.pipeline.steps import make_bootstrap_meta_step


_DEFAULT_STEPS = [
    make_bootstrap_meta_step(
        profile_defaults={"auto_filter": True, "freeze_header": True},
    ),
]


def _args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sheets-example-json-to-xlsx",
        description=(
            "Reference shortcut command: write a JSON directory to XLSX using "
            "the supported wrapper pattern."
        ),
    )
    parser.add_argument("input_dir", help="Directory with .json files")
    parser.add_argument("-o", "--output", required=True, help="Output .xlsx file")
    parser.add_argument("--input-kind", default="json_dir", choices=["json", "json_dir"])
    parser.add_argument("--config", default=None, help="Pipeline YAML (overrides defaults)")
    parser.add_argument("--no-defaults", action="store_true", help="Suppress default pipeline")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)

    if args.config:
        steps = build_steps_from_yaml(args.config)
    elif args.no_defaults:
        steps = None
    else:
        steps = _DEFAULT_STEPS

    orchestrate(
        input={"kind": args.input_kind, "path": args.input_dir},
        output={"kind": "xlsx", "path": args.output},
        steps=steps,
    )
    print(f"[example-json-to-xlsx] Wrote XLSX: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
