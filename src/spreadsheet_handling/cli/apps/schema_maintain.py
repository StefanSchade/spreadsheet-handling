"""CLI adapter for schema-maintenance commands.

Schema maintenance is intentionally exposed separately from
user-configurable pipelines. This module parses CLI arguments, maps them to
an application request, invokes the use case, and serializes its report.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any

from spreadsheet_handling.application.schema_maintenance import run_schema_maintenance
from spreadsheet_handling.cli.runtime import run_cli
from spreadsheet_handling.domain.schema_maintenance import (
    ColumnPlacement,
    ReorderSpec,
    SchemaMaintenanceReport,
    SchemaMaintenanceRequest,
    SchemaOperationKind,
    WriteIntent,
)

DISCARD_PATH = "__discard__"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    request = _request_from_args(args)

    report = run_schema_maintenance(
        input={"kind": args.in_kind, "path": args.in_path},
        output=_output_from_args(args),
        request=request,
    )

    _emit_report(report, args.report)
    return 1 if report.blocked else 0


def cli_entry() -> None:
    run_cli(main)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sheets-schema-maintain",
        description="Run private schema maintenance operations through the orchestrator.",
    )
    parser.add_argument("--in-kind", required=True)
    parser.add_argument("--in-path", required=True)
    parser.add_argument("--out-kind")
    parser.add_argument("--out-path")
    parser.add_argument(
        "--op",
        required=True,
        choices=[kind.value for kind in SchemaOperationKind],
    )
    parser.add_argument("--frame", required=True)
    parser.add_argument("--source-column")
    parser.add_argument("--target-column")
    parser.add_argument("--default", default="")
    placement = parser.add_mutually_exclusive_group()
    placement.add_argument("--insert-before")
    placement.add_argument("--insert-after")
    parser.add_argument("--column", action="append", default=[])
    parser.add_argument(
        "--reorder-mode",
        choices=["complete", "listed_first", "listed_last"],
        default="complete",
    )
    parser.add_argument("--prune", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="write", action="store_false", default=False)
    mode.add_argument("--write", dest="write", action="store_true")
    parser.add_argument("--report")
    return parser


def _request_from_args(args: argparse.Namespace) -> SchemaMaintenanceRequest:
    kind = SchemaOperationKind(args.op)
    return SchemaMaintenanceRequest(
        kind=kind,
        target_frame=args.frame,
        source_column=args.source_column,
        target_column=args.target_column,
        default_value=args.default,
        placement=_placement_from_args(args, kind),
        reorder=_reorder_from_args(args, kind),
        prune=args.prune,
        write_intent=WriteIntent.WRITE if args.write else WriteIntent.DRY_RUN,
    )


def _placement_from_args(
    args: argparse.Namespace,
    kind: SchemaOperationKind,
) -> ColumnPlacement | None:
    if args.insert_before:
        return ColumnPlacement(mode="before", column=args.insert_before)
    if args.insert_after:
        return ColumnPlacement(mode="after", column=args.insert_after)
    if kind is SchemaOperationKind.ADD_COLUMN:
        return ColumnPlacement()
    return None

def _reorder_from_args(
    args: argparse.Namespace,
    kind: SchemaOperationKind,
) -> ReorderSpec | None:
    if kind is not SchemaOperationKind.REORDER_COLUMNS:
        return None
    return ReorderSpec(mode=args.reorder_mode, columns=tuple(args.column))


def _output_from_args(args: argparse.Namespace) -> dict[str, str]:
    if not args.write:
        return {"kind": "discard", "path": DISCARD_PATH}
    missing = [name for name in ("out_kind", "out_path") if not getattr(args, name)]
    if missing:
        rendered = ", ".join("--" + name.replace("_", "-") for name in missing)
        raise SystemExit(f"Write mode requires {rendered}")
    return {"kind": args.out_kind, "path": args.out_path}


def _emit_report(report: SchemaMaintenanceReport, path: str | None) -> None:
    text = json.dumps(_jsonable(report), indent=2, sort_keys=True)
    if path:
        report_path = Path(path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text + "\n", encoding="utf-8")
        return
    print(text)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


if __name__ == "__main__":
    cli_entry()
