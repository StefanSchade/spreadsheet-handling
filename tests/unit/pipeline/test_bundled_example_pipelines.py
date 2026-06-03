"""Smoke checks for the bundled example pipeline YAMLs.

Examples shipped under ``src/spreadsheet_handling/examples/`` document the
public pipeline surface. They must parse cleanly and resolve every
``step:`` to a known registry entry under the v2 FK-helper runtime
contract (``FTR-FK-HELPER-DOCS-DEMO-REALIGNMENT-P5``). The same checks
also pin the producer-before-consumer ordering: any pipeline that uses an
FK-helper primitive must run a producer step (``infer_fk_relations`` or
``configure_fk_helpers``) earlier in the same pipeline.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from spreadsheet_handling.pipeline import build_steps_from_config

EXAMPLES_DIR = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "spreadsheet_handling"
    / "examples"
)

_FK_HELPER_CONSUMERS = frozenset(
    {
        "add_fk_helpers",
        "reorder_fk_helpers",
        "validate_fk_helpers",
        "remove_fk_helpers",
    }
)

_FK_POLICY_PRODUCERS = frozenset(
    {
        "infer_fk_relations",
        "configure_fk_helpers",
    }
)


def _iter_step_lists(doc: dict) -> list[tuple[str, list[dict]]]:
    """Yield (label, step_list) for every pipeline declaration in *doc*."""
    out: list[tuple[str, list[dict]]] = []
    if isinstance(doc, dict):
        if isinstance(doc.get("pipeline"), list):
            out.append(("pipeline", doc["pipeline"]))
        pipelines = doc.get("pipelines")
        if isinstance(pipelines, dict):
            for name, steps in pipelines.items():
                if isinstance(steps, list):
                    out.append((f"pipelines.{name}", steps))
    return out


def _producer_before_consumer(steps: list[dict]) -> None:
    seen_producer = False
    for raw in steps:
        if not isinstance(raw, dict):
            continue
        step_id = raw.get("step")
        if step_id in _FK_POLICY_PRODUCERS:
            seen_producer = True
        elif step_id in _FK_HELPER_CONSUMERS and step_id != "remove_fk_helpers":
            # `remove_fk_helpers` can read provenance persisted in a workbook
            # produced by an earlier pipeline run; the others must see a
            # producer earlier in the same pipeline.
            assert seen_producer, (
                f"FK-helper consumer {step_id!r} appears before any FK policy "
                f"producer ({sorted(_FK_POLICY_PRODUCERS)})"
            )


@pytest.mark.parametrize(
    "example_yaml",
    sorted(p.name for p in EXAMPLES_DIR.glob("*.yml")),
)
def test_bundled_example_pipeline_parses_and_builds(example_yaml: str) -> None:
    """Every bundled example YAML must parse and resolve to known steps."""
    path = EXAMPLES_DIR / example_yaml
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    pipelines = _iter_step_lists(doc)
    assert pipelines, f"{example_yaml!r} declares no pipeline"

    for label, steps in pipelines:
        # Resolves every `step:` identifier through the registry. Unknown
        # steps raise here.
        build_steps_from_config(steps)
        _producer_before_consumer(steps)


@pytest.mark.parametrize(
    "step_id",
    sorted(_FK_HELPER_CONSUMERS | _FK_POLICY_PRODUCERS),
)
def test_fk_helper_step_registered(step_id: str) -> None:
    """Producers and consumers referenced by docs/demo must stay registered."""
    from spreadsheet_handling.pipeline.registry import REGISTRY

    assert step_id in REGISTRY, (
        f"{step_id!r} must remain a registered pipeline step under the "
        f"v2 FK-helper runtime contract"
    )
