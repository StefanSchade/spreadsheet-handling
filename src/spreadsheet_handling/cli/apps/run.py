from __future__ import annotations

import argparse
import logging
from typing import Any, Dict, Optional

import yaml

from spreadsheet_handling.io_backends.router import get_loader, get_saver
from spreadsheet_handling.pipeline import (
    run_pipeline,
    build_steps_from_config,
    build_steps_from_yaml,
)
from spreadsheet_handling.cli.logging_utils import setup_logging
from spreadsheet_handling.cli.runtime import run_cli

log = logging.getLogger("sheets.run")


# ---------------------------------------------------------------------
# I/O selection helpers
# ---------------------------------------------------------------------
def _select_io_config(config: Dict[str, Any], profile: str | None) -> Dict[str, Any]:
    io = (config or {}).get("io") or {}
    if profile:
        profiles = io.get("profiles") or {}
        sel = profiles.get(profile)
        if not sel:
            raise SystemExit(f"Unknown profile '{profile}'. Available: {list(profiles)}")
        return sel
    return io


def _maybe_load_inline_config_from_pipeline_yaml(pipeline_yaml: str) -> Dict[str, Any]:
    with open(pipeline_yaml, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    out: Dict[str, Any] = {}
    if isinstance(raw.get("io"), dict):
        out["io"] = raw["io"]
    if isinstance(raw.get("pipelines"), dict):
        out["pipelines"] = raw["pipelines"]
    if isinstance(raw.get("pipeline"), list):
        out["pipeline"] = raw["pipeline"]
    return out


def _select_pipeline_steps(
        config: Dict[str, Any],
        *,
        pipeline_name: str | None,
        pipeline_yaml: str | None,
        profile: str | None,
):
    if pipeline_yaml:
        return build_steps_from_yaml(pipeline_yaml)

    if pipeline_name:
        pipelines = (config.get("pipelines") or {})
        specs = pipelines.get(pipeline_name)
        if specs is None:
            raise SystemExit(f"Unknown pipeline '{pipeline_name}'. Available: {list(pipelines)}")
        return build_steps_from_config(specs)

    if profile:
        prof_spec = (((config or {}).get("io") or {}).get("profiles") or {}).get(profile) or {}
        prof_pipeline_name = prof_spec.get("pipeline")
        if prof_pipeline_name:
            pipelines = (config.get("pipelines") or {})
            specs = pipelines.get(prof_pipeline_name)
            if specs is None:
                raise SystemExit(
                    f"Profile '{profile}' refers to unknown pipeline '{prof_pipeline_name}'. "
                    f"Available: {list(pipelines)}"
                )
            return build_steps_from_config(specs)

    specs = (config or {}).get("pipeline") or []
    return build_steps_from_config(specs)

# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sheets-run",
        description="Generic runner for standard/custom pipelines (I/O + steps).",
    )

    # yaml config options
    parser.add_argument("--config", help="Path to a config YAML. May include io, pipelines, pipeline.")
    parser.add_argument("--pipeline", help="Name of pipelines[...] in the config.")
    parser.add_argument( "--steps", help="Path to a YAML defining steps for ad hoc run. May also include io")
    parser.add_argument( "--pipeline", help="Name of a pipeline defined under 'pipelines:' in --config.")
    parser.add_argument("--profile", help="Name of 'io.profiles[...]' in --config (binds IO and optional default pipeline).")

    # deprecated configs
    parser.add_argument("--pipeline-yaml", dest="steps", help=argparse.SUPPRESS)

    # path overrides (override selected profile/top-level io)
    parser.add_argument("--in-kind", help="Override input.kind (e.g., json_dir, csv_dir, xlsx)")
    parser.add_argument("--in-path", help="Override input.path")
    parser.add_argument("--out-kind", help="Override output.kind (e.g., json_dir, csv_dir, xlsx)")
    parser.add_argument("--out-path", help="Override output.path")

    # logging options
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (repeatable)")
    parser.add_argument("--debug", action="store_true", help="Show full tracebacks on errors")

    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    # Load config: prefer explicit --config; otherwise accept 'io' from --pipeline-yaml
    config: Dict[str, Any] = {}
    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    elif args.pipeline_yaml:
        inline = _maybe_load_inline_config_from_pipeline_yaml(args.pipeline_yaml)
        if "io" in inline:
            config = {"io": inline["io"]}

    # 1) start with whatever is in the config (or empty)
    io_cfg = _select_io_config(config, args.profile) if config else {}

    # 2) build working dicts
    inp = dict((io_cfg.get("input") or {}))
    out = dict((io_cfg.get("output") or {}))

    # 3) apply CLI overrides (these should always win)
    if args.in_kind:
        inp["kind"] = args.in_kind
    if args.in_path:
        inp["path"] = args.in_path
    if args.out_kind:
        out["kind"] = args.out_kind
    if args.out_path:
        out["path"] = args.out_path

    # 4) validate *after* overrides
    missing = [k for k in ("kind", "path") if k not in inp] + [f"out.{k}" for k in ("kind", "path") if k not in out]
    if missing:
        raise SystemExit(
            "Missing I/O configuration. Provide --config/--pipeline-yaml with 'io', or add CLI overrides."
        )

    # Choose loader/saver
    loader = get_loader(str(inp["kind"]))
    saver = get_saver(str(out["kind"]))

    # Build steps
    steps = _select_pipeline_steps(
        config,
        pipeline_name=args.pipeline,
        pipeline_yaml=args.pipeline_yaml,
        profile=args.profile,
    )

    # Run
    frames = loader(str(inp["path"]))
    frames = run_pipeline(frames, steps)
    saver(frames, str(out["path"]))

    log.info("Done. Wrote output to %s", out["path"])
    return 0


if __name__ == "__main__":
    run_cli(main)
