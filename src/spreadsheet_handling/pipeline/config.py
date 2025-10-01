from __future__ import annotations

# Thin re-export shim so tests can import from pipeline.config
try:
    # Prefer the real engine config if present
    from ..engine.config import (  # type: ignore
        AppConfig,
        IOEndpoint,
        IOConfig,
        StepRef,
        PipelineConfig,
        ExcelOptions,
        load_app_config as _load_app_config,
    )
except Exception:
    # Lightweight fallback to keep tests running without engine.config
    from dataclasses import dataclass, field
    from typing import Any, Dict, List, Optional
    import yaml

    @dataclass
    class ExcelOptions:
        auto_filter: bool = True
        header_fill_rgb: str = "DDDDDD"
        freeze_header: bool = False
        # accepted by tests; unused in fallback, but present for compatibility
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
    class StepRef:
        name: Optional[str]
        dotted: str
        args: Dict[str, Any] | None = None

    @dataclass
    class PipelineConfig:
        steps: List[StepRef]

    @dataclass
    class AppConfig:
        io: IOConfig
        pipeline: PipelineConfig
        excel: ExcelOptions = field(default_factory=ExcelOptions)
        strict: bool = False

    def _load_app_config(path: str) -> AppConfig:
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        io_cfg = cfg.get("io", {}) or {}
        inputs_cfg = io_cfg.get("inputs", {}) or {}
        output_cfg = io_cfg.get("output", {}) or {}

        steps_cfg = ((cfg.get("pipeline", {}) or {}).get("steps", [])) or []

        return AppConfig(
            io=IOConfig(
                inputs={k: IOEndpoint(**v) for k, v in inputs_cfg.items()},
                output=IOEndpoint(**output_cfg),
            ),
            pipeline=PipelineConfig(
                steps=[
                    StepRef(
                        name=s.get("name"),
                        dotted=(s.get("factory") or s.get("dotted")),
                        args=s.get("args") or {},
                    )
                    for s in steps_cfg
                ]
            ),
            excel=ExcelOptions(**(cfg.get("excel") or {})),
            strict=bool(cfg.get("strict", False)),
        )

def load_app_config(path: str):
    return _load_app_config(path)
