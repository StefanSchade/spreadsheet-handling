import sys
import textwrap
import importlib
from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.domain import ingress as ingress_package
from spreadsheet_handling.domain.ingress import coordinator as ingress_coordinator
from spreadsheet_handling.domain.ingress import legend_blocks as ingress_legend_rule
from spreadsheet_handling.pipeline import build_steps_from_config, run_pipeline
from spreadsheet_handling.pipeline import registry as pipeline_registry
from spreadsheet_handling.pipeline import steps as pipeline_steps
from spreadsheet_handling.pipeline.steps import make_frames_target_step

pytestmark = pytest.mark.ftr("FTR-TEST-HARNESS")

_INGRESS_TARGETS = (
    (
        "spreadsheet_handling.domain.ingress:run_domain_ingress",
        ingress_package,
        "run_domain_ingress",
    ),
    (
        "spreadsheet_handling.domain.ingress.coordinator:run_domain_ingress",
        ingress_coordinator,
        "run_domain_ingress",
    ),
    (
        "spreadsheet_handling.domain.ingress.legend_blocks:"
        "normalize_legend_blocks_shape",
        ingress_legend_rule,
        "normalize_legend_blocks_shape",
    ),
)


def test_dotted_path_step(tmp_path: Path, monkeypatch):
    # 1) Write a tiny module to disk.
    moddir = tmp_path / "extsteps"
    moddir.mkdir()
    (moddir / "__init__.py").write_text("", encoding="utf-8")
    (moddir / "steps.py").write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass
            from typing import Any, Dict
            import pandas as pd

            # minimal BoundStep-compatible factory
            def make_keep_columns_step(*, table: str, columns: list[str], name: str = "keep_columns"):
                from spreadsheet_handling.pipeline.types import BoundStep
                Frames = dict[str, pd.DataFrame]
                cfg = {"table": table, "columns": columns}

                def run(frames: Frames) -> Frames:
                    df = frames.get(table)
                    if df is None:
                        return frames
                    out = dict(frames)
                    keep = [c for c in columns if c in df.columns]
                    out[table] = df.loc[:, keep]
                    return out

                return BoundStep(name=name, config=cfg, fn=run)

            def mark_external_plugin(frames, *, marker: str):
                out = dict(frames)
                out["_plugin_marker"] = marker
                return out
            """
        ),
        encoding="utf-8",
    )

    # 2) Add the import path and import the module.
    sys.path.insert(0, str(tmp_path))
    try:
        importlib.import_module("extsteps.steps")  # sanity

        # 3) Build the pipeline from a dotted path.
        cfg = [
            {
                "step": "extsteps.steps:make_keep_columns_step",
                "table": "A",
                "columns": ["id", "name"],
            },
            {
                "step": "plugin",
                "dotted": "extsteps.steps:mark_external_plugin",
                "args": {"marker": "external"},
            },
        ]
        steps = build_steps_from_config(cfg)

        frames = {"A": pd.DataFrame({"id": [1, 2], "name": ["x", "y"], "dropme": [0, 0]})}
        out = run_pipeline(frames, steps)

        assert set(out["A"].columns) == {"id", "name"}  # external transform applied
        assert "dropme" not in out["A"].columns
        assert out["_plugin_marker"] == "external"
    finally:
        # Clean up.
        sys.path = [p for p in sys.path if p != str(tmp_path)]


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5")
@pytest.mark.parametrize(
    ("dotted", "owner", "attribute"),
    _INGRESS_TARGETS,
)
@pytest.mark.parametrize("surface", ["plugin", "colon_factory"])
def test_framework_ingress_namespace_is_rejected_before_invocation(
    dotted,
    owner,
    attribute,
    surface,
    monkeypatch,
):
    invoked = False

    def invocation_sentinel(*args, **kwargs):
        nonlocal invoked
        invoked = True
        raise AssertionError("framework ingress callable was invoked")

    monkeypatch.setattr(owner, attribute, invocation_sentinel)
    spec = (
        {"step": "plugin", "dotted": dotted}
        if surface == "plugin"
        else {"step": dotted, "frames": {"_meta": {"legend_blocks": None}}}
    )

    with pytest.raises(
        ValueError,
        match="framework-internal and not configuration/plugin-addressable",
    ):
        build_steps_from_config([spec])

    assert invoked is False


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5")
@pytest.mark.parametrize(
    "dotted",
    [
        "spreadsheet_handling.domain.ingress.run_domain_ingress",
        "spreadsheet_handling.domain.ingress.coordinator.run_domain_ingress",
        (
            "spreadsheet_handling.domain.ingress.legend_blocks."
            "normalize_legend_blocks_shape"
        ),
    ],
)
def test_framework_ingress_namespace_is_rejected_in_final_dot_plugin_form(dotted):
    with pytest.raises(
        ValueError,
        match="framework-internal and not configuration/plugin-addressable",
    ):
        build_steps_from_config([{"step": "plugin", "dotted": dotted}])


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5")
@pytest.mark.parametrize("surface", ["plugin", "colon_factory"])
def test_framework_ingress_rejection_precedes_import(surface, monkeypatch):
    def fail_import(module_path):
        raise AssertionError(f"unexpected import of {module_path}")

    monkeypatch.setattr(pipeline_steps.importlib, "import_module", fail_import)
    dotted = "spreadsheet_handling.domain.ingress:run_domain_ingress"
    spec = (
        {"step": "plugin", "dotted": dotted}
        if surface == "plugin"
        else {"step": dotted, "frames": {}}
    )

    with pytest.raises(
        ValueError,
        match="framework-internal and not configuration/plugin-addressable",
    ):
        build_steps_from_config([spec])


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5")
@pytest.mark.parametrize(
    "dotted",
    [
        " external.steps:run",
        "external.steps:run ",
        "external.steps:",
        ":run",
        "external.steps::run",
        "external.steps.",
    ],
)
def test_malformed_plugin_dotted_references_fail_before_import(dotted, monkeypatch):
    def fail_import(module_path):
        raise AssertionError(f"unexpected import of {module_path}")

    monkeypatch.setattr(pipeline_steps.importlib, "import_module", fail_import)
    with pytest.raises(ValueError, match="Dotted callable reference"):
        build_steps_from_config([{"step": "plugin", "dotted": dotted}])


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5")
@pytest.mark.parametrize(
    "dotted",
    [
        " external.steps:make_step",
        "external.steps:make_step ",
        "external.steps:",
        ":make_step",
        "external.steps::make_step",
        "external.steps.:make_step",
    ],
)
def test_malformed_colon_factory_references_fail_before_import(dotted, monkeypatch):
    def fail_import(module_path):
        raise AssertionError(f"unexpected import of {module_path}")

    monkeypatch.setattr(pipeline_registry.importlib, "import_module", fail_import)
    with pytest.raises(ValueError, match="Dotted callable reference"):
        build_steps_from_config([{"step": dotted}])


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5")
def test_existing_internal_plugin_remains_addressable():
    steps = build_steps_from_config(
        [
            {
                "step": "plugin",
                "dotted": (
                    "tools.domain_contracts.workbook:"
                    "normalize_reimported_contract_frames"
                ),
            }
        ]
    )
    frames = {"payload": pd.DataFrame({"id": [1]}), "_meta": {"kept": True}}

    out = run_pipeline(frames, steps)

    assert out["payload"].to_dict(orient="records") == [{"id": 1}]
    assert out["_meta"] == {"kept": True}


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5")
def test_existing_internal_colon_factory_remains_addressable():
    steps = build_steps_from_config(
        [{"step": "spreadsheet_handling.pipeline.steps:make_identity_step"}]
    )
    payload = pd.DataFrame({"id": [1], "value": ["kept"]})
    frames = {"payload": payload, "_meta": {"kept": True}}

    assert len(steps) == 1
    assert steps[0].name == "identity"
    out = run_pipeline(frames, steps)
    assert out is frames
    assert out["payload"] is payload
    assert out["payload"].to_dict(orient="records") == [{"id": 1, "value": "kept"}]
    assert out["_meta"] == {"kept": True}


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5")
def test_registered_short_name_remains_addressable():
    steps = build_steps_from_config([{"step": "identity"}])
    payload = pd.DataFrame({"id": [1], "value": ["kept"]})
    frames = {"payload": payload, "_meta": {"kept": True}}

    assert len(steps) == 1
    assert steps[0].name == "identity"
    out = run_pipeline(frames, steps)
    assert out is frames
    assert out["payload"] is payload
    assert out["payload"].to_dict(orient="records") == [{"id": 1, "value": "kept"}]
    assert out["_meta"] == {"kept": True}


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5")
def test_direct_python_callable_target_is_not_treated_as_dotted_config():
    def mark(frames, *, marker):
        out = dict(frames)
        out["marker"] = marker
        return out

    step = make_frames_target_step(target=mark, name="mark", marker="direct")

    assert step({}) == {"marker": "direct"}


@pytest.mark.ftr("FTR-LEGEND-BLOCKS-RESOLVED-SHAPE-CORRECTION-P5")
def test_plugin_dotted_parameter_requires_a_string():
    with pytest.raises(TypeError, match="Dotted callable reference must be a string"):
        build_steps_from_config([{"step": "plugin", "dotted": lambda frames: frames}])
