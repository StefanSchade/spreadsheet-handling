from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.cli.runtime import run_cli
from spreadsheet_handling.domain.schema_maintenance import (
    ColumnPlacement,
    ReorderSpec,
    SchemaMaintenanceReport,
    SchemaMaintenanceRequest,
    SchemaMaintenanceResult,
    SchemaOperationKind,
    WriteIntent,
    apply_schema_maintenance,
)
from spreadsheet_handling.pipeline.types import BoundStep, Frames

PRIVATE_STEP_NAME = "_schema_maintenance_private"
DISCARD_PATH = "__discard__"


class SchemaMaintenanceBlocked(RuntimeError):
    def __init__(self, report: SchemaMaintenanceReport) -> None:
        super().__init__("Schema maintenance operation blocked")
        self.report = report


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    request = _request_from_args(args)
    collector: list[SchemaMaintenanceReport] = []
    step = _build_private_step(request, collector)

    try:
        orchestrate(
            input={"kind": args.in_kind, "path": args.in_path},
            output=_output_from_args(args),
            steps=[step],
        )
    except SchemaMaintenanceBlocked:
        _emit_report(_require_report(collector), args.report)
        return 1

    _emit_report(_require_report(collector), args.report)
    return 0


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
        placement=_placement_from_args(args),
        reorder=_reorder_from_args(args),
        prune=args.prune,
        write_intent=WriteIntent.WRITE if args.write else WriteIntent.DRY_RUN,
    )


def _placement_from_args(args: argparse.Namespace) -> ColumnPlacement | None:
    if args.insert_before:
        return ColumnPlacement(mode="before", column=args.insert_before)
    if args.insert_after:
        return ColumnPlacement(mode="after", column=args.insert_after)
    if args.op == SchemaOperationKind.ADD_COLUMN.value:
        return ColumnPlacement()
    return None


def _reorder_from_args(args: argparse.Namespace) -> ReorderSpec | None:
    if args.op != SchemaOperationKind.REORDER_COLUMNS.value:
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


def _build_private_step(
    request: SchemaMaintenanceRequest,
    collector: list[SchemaMaintenanceReport],
) -> BoundStep:
    def run(frames: Frames) -> Frames:
        result: SchemaMaintenanceResult = apply_schema_maintenance(frames, request)
        collector.append(result.report)
        if result.report.blocked:
            raise SchemaMaintenanceBlocked(result.report)
        return result.frames

    return BoundStep(
        name=PRIVATE_STEP_NAME,
        config={"operation": request.kind.value, "target_frame": request.target_frame},
        fn=run,
    )


def _require_report(collector: list[SchemaMaintenanceReport]) -> SchemaMaintenanceReport:
    if not collector:
        raise RuntimeError("Schema maintenance did not produce a report")
    return collector[-1]


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
