from __future__ import annotations

import argparse
import logging
from typing import Any, Dict

import yaml

from spreadsheet_handling.io_backends.router import get_loader, get_saver
from spreadsheet_handling.pipeline import (
    run_pipeline,
    build_steps_from_config,
    build_steps_from_yaml,
)

log = logging.getLogger("sheets.run")


def _setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s  %(name)s:%(message)s")


def _select_io_config(config: Dict[str, Any], profile: str | None) -> Dict[str, Any]:
    """
    Returns an IO config dict with keys: input {kind,path}, output {kind,path}.
    If 'profile' is set, takes io.profiles[profile], otherwise takes top-level io.
    """
    io = (config or {}).get("io") or {}
    if profile:
        profiles = io.get("profiles") or {}
        sel = profiles.get(profile)
        if not sel:
            raise SystemExit(f"Unknown profile '{profile}'. Available: {list(profiles)}")
        return sel
    return io


def _select_pipeline_steps(
    config: Dict[str, Any],
    *,
    pipeline_name: str | None,
    pipeline_yaml: str | None,
    profile: str | None,
) :
    """
    Build steps from either:
      - a dedicated pipeline YAML (`--pipeline-yaml`), or
      - config.pipelines[<pipeline_name>], or
      - profile-bound default pipeline (io.profiles[profile].pipeline), or
      - config.pipeline (single unnamed pipeline spec)
    """
    if pipeline_yaml:
        return build_steps_from_yaml(pipeline_yaml)

    # Named pipeline wins if provided
    if pipeline_name:
        pipelines = (config.get("pipelines") or {})
        specs = pipelines.get(pipeline_name)
        if specs is None:
            raise SystemExit(f"Unknown pipeline '{pipeline_name}'. Available: {list(pipelines)}")
        return build_steps_from_config(specs)

    # Fall back to profile-bound default pipeline, if any
    if profile:
        profile_spec = (((config or {}).get("io") or {}).get("profiles") or {}).get(profile) or {}
        prof_pipeline_name = profile_spec.get("pipeline")
        if prof_pipeline_name:
            pipelines = (config.get("pipelines") or {})
            specs = pipelines.get(prof_pipeline_name)
            if specs is None:
                raise SystemExit(
                    f"Profile '{profile}' refers to unknown pipeline '{prof_pipeline_name}'. "
                    f"Available: {list(pipelines)}"
                )
            return build_steps_from_config(specs)

    # Finally, allow a single unnamed pipeline at top-level
    specs = (config or {}).get("pipeline") or []
    return build_steps_from_config(specs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sheets-run",
        description="Generic runner for standard/custom pipelines (I/O + steps).",
    )
    parser.add_argument("--config", help="Path to a config YAML (may include io, pipelines, pipeline).")
    parser.add_argument("--pipeline-yaml", help="Path to a pipeline YAML (overrides config pipelines).")
    parser.add_argument("--profile", help="Name of io.profiles[...] in the config.")
    parser.add_argument("--pipeline", help="Name of pipelines[...] in the config.")
    # path overrides (override selected profile/top-level io)
    parser.add_argument("--in-kind", help="Override input.kind (e.g., json_dir, csv_dir, xlsx)")
    parser.add_argument("--in-path", help="Override input.path")
    parser.add_argument("--out-kind", help="Override output.kind (e.g., json_dir, csv_dir, xlsx)")
    parser.add_argument("--out-path", help="Override output.path")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (repeatable)")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    # Load config file (optional)
    config: Dict[str, Any] = {}
    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    # Select I/O (profile or top-level), then apply overrides
    io_cfg = _select_io_config(config, args.profile)
    if not io_cfg:
        raise SystemExit("Missing I/O configuration. Provide --config with 'io' or 'io.profiles' or use overrides.")

    inp = dict(io_cfg.get("input") or {})
    out = dict(io_cfg.get("output") or {})

    # CLI overrides
    if args.in_kind: inp["kind"] = args.in_kind
    if args.in_path: inp["path"] = args.in_path
    if args.out_kind: out["kind"] = args.out_kind
    if args.out_path: out["path"] = args.out_path

    # Validate resulting IO
    if not inp or not out:
        raise SystemExit("I/O config incomplete. Need input.{kind,path} and output.{kind,path}.")
    if "kind" not in inp or "path" not in inp or "kind" not in out or "path" not in out:
        raise SystemExit("I/O config incomplete. Need input.{kind,path} and output.{kind,path}.")

    # Choose loader/saver
    loader = get_loader(str(inp["kind"]))
    saver = get_saver(str(out["kind"]))

    # Build steps (supports profile-bound default pipeline)
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
    raise SystemExit(main())
