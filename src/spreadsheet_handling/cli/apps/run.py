from __future__ import annotations

import argparse
import logging
from typing import Any, Dict, Optional

import yaml
import os

from spreadsheet_handling.application.orchestrator import orchestrate
from spreadsheet_handling.pipeline import (
    build_steps_from_config,
    build_steps_from_yaml,
)
from spreadsheet_handling.cli.logging_utils import setup_logging
from spreadsheet_handling.cli.runtime import run_cli

log = logging.getLogger("sheets.run")


# ---------------------------------------------------------------------
# I/O selection helpers
# ---------------------------------------------------------------------

def _load_config(args):
    """Prefer the explicit config --config; otherwise accept 'io' from --steps"""
    config: Dict[str, Any] = {}
    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    elif args.steps and os.path.exists(args.steps):
        inline = _maybe_load_inline_config_from_steps_yaml(args.steps)
        if "io" in inline:
            config = {"io": inline["io"]}
    return config

def _maybe_load_inline_config_from_steps_yaml(steps_yaml: str) -> Dict[str, Any]:
    with open(steps_yaml, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    out: Dict[str, Any] = {}
    if isinstance(raw.get("io"), dict):
        out["io"] = raw["io"]
    if isinstance(raw.get("pipelines"), dict):
        out["pipelines"] = raw["pipelines"]
    if isinstance(raw.get("pipeline"), list):
        out["pipeline"] = raw["pipeline"]
    return out

def _select_io_config(config: Dict[str, Any], profile: str | None) -> Dict[str, Any]:
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
        steps_yaml: str | None,
        profile: str | None,
    ):
    """Extract pipeline specifications, determine the relevant pipeline and extract the steps."""
    if steps_yaml:
        return build_steps_from_yaml(steps_yaml) # Ad-hoc steps file wins
    spec_of_pipelines_by_name = (config or {}).get("pipelines") or {}
    # Determine effective pipeline name (explicit > from profile > None)
    effective_name = pipeline_name or _pipeline_name_from_profile(config, profile)
    # Resolve specs
    if effective_name:
        specs = _get_pipeline_specs_or_die(spec_of_pipelines_by_name, effective_name, profile)
    else:
        # fallback to top-level `pipeline: [...]` (ad-hoc list in config)
        specs = (config or {}).get("pipeline") or []
    # Build
    return build_steps_from_config(specs)

def _pipeline_name_from_profile(config: Dict[str, Any], profile: str | None) -> str | None:
    """Profiles may declare a default pipeline, or they may not."""
    if not profile:
        return None
    io = (config or {}).get("io") or {}
    profiles = io.get("profiles") or {}
    prof_spec = profiles.get(profile) or {}
    return prof_spec.get("pipeline")


def _get_pipeline_specs_or_die(pipelines: Dict[str, Any], name: str, profile: str | None) -> list[dict]:
    """In case the pipeline specs are missing, fail."""
    specs = pipelines.get(name)
    if specs is not None:
        return specs
    # Construct a precise error depending on whether this came from --pipeline or from profile
    if profile:
        raise SystemExit(
            f"Profile '{profile}' refers to unknown pipeline '{name}'. "
            f"Available: {list(pipelines)}"
        )
    raise SystemExit(
        f"Unknown pipeline '{name}'. Available: {list(pipelines)}"
    )

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
    parser.add_argument( "--pipeline", help="Name of a pipeline defined under 'pipelines:' in --config.")
    parser.add_argument( "--steps", help="Path to a YAML defining steps for ad hoc run. May also include io")
    parser.add_argument("--profile", help="Name of 'io.profiles[...]' in --config (binds IO and optional default pipeline).")

    # deprecated configs
    parser.add_argument("--pipeline-yaml", dest="steps", help=argparse.SUPPRESS)

    # path overrides (override selected profile/top-level io)
    parser.add_argument("--in-kind", help="Override input.kind (e.g., json_dir, yaml_dir, xlsx, ods, calc)")
    parser.add_argument("--in-path", help="Override input.path")
    parser.add_argument("--out-kind", help="Override output.kind (e.g., json_dir, yaml_dir, xlsx, ods, calc)")
    parser.add_argument("--out-path", help="Override output.path")

    # logging options
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (repeatable)")
    parser.add_argument("--debug", action="store_true", help="Show full tracebacks on errors")

    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    config = _load_config(args)

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
            "Missing I/O configuration. Provide --config/--steps with 'io', or add CLI overrides."
        )

    # Build steps
    steps = _select_pipeline_steps(
        config,
        pipeline_name=args.pipeline,
        steps_yaml=args.steps,
        profile=args.profile,
    )

    # Run via unified orchestrator
    orchestrate(input=inp, output=out, steps=steps or None)

    log.info("Done. Wrote output to %s", out["path"])
    return 0

if __name__ == "__main__":
    run_cli(main)
