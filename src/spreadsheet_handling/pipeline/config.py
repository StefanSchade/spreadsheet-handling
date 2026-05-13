from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import yaml


@dataclass
class ExcelOptions:
    auto_filter: bool = True
    header_fill_rgb: str = "DDDDDD"
    freeze_header: bool = False
    helper_fill_rgb: Optional[str] = None

@dataclass
class IOEndpoint:
    kind: str
    path: str
    options: Dict[str, Any] | None = None

@dataclass
class IOConfig:
    inputs: Dict[str, IOEndpoint]
    output: IOEndpoint

@dataclass
class AppConfig:
    io: IOConfig
    pipeline: list[dict[str, Any]] = field(default_factory=list)
    excel: ExcelOptions = field(default_factory=ExcelOptions)
    strict: bool = False


def load_app_config(path: str) -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    io_cfg = cfg.get("io", {}) or {}
    inputs_cfg = io_cfg.get("inputs", {}) or {}
    output_cfg = io_cfg.get("output", {}) or {}

    pipeline_cfg = cfg.get("pipeline") or []
    if not isinstance(pipeline_cfg, list):
        raise ValueError("YAML key 'pipeline' must be a step list using the canonical step: dialect.")

    return AppConfig(
        io=IOConfig(
            inputs={k: IOEndpoint(**v) for k, v in inputs_cfg.items()},
            output=IOEndpoint(**output_cfg),
        ),
        pipeline=[dict(step) for step in pipeline_cfg],
        excel=ExcelOptions(**(cfg.get("excel") or {})),
        strict=bool(cfg.get("strict", False)),
    )
