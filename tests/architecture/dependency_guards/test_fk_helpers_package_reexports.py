"""Guard: the fk_helpers package preserves its public + documented symbol paths.

FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-FK-HELPERS-P5 split the single
``fk_helpers`` module into a package. Callers (pipeline registry, tests) and
the ``meta_registry.yaml`` derived-channel producer/consumer references depend
on these dotted paths resolving through ``fk_helpers/__init__.py`` regardless
of the internal file layout. This guard fails fast if a future internal move
forgets to re-export one of them.
"""
from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.ftr("FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-FK-HELPERS-P5")

_PACKAGE = "spreadsheet_handling.domain.transformations.fk_helpers"

# Names that must remain attributes of the package root. enrich_helpers /
# drop_helpers are imported by pipeline.steps and tests; _write_helper_provenance
# is the documented `derived` producer symbol path in meta_registry.yaml.
_REQUIRED_SYMBOLS = ("enrich_helpers", "drop_helpers", "_write_helper_provenance")


def test_public_and_documented_symbols_resolve_through_package():
    pkg = importlib.import_module(_PACKAGE)
    for name in _REQUIRED_SYMBOLS:
        assert hasattr(pkg, name), (
            f"{_PACKAGE}.{name} must stay accessible via the package __init__; "
            f"it is part of the public/registry/meta-registry contract."
        )
        assert callable(getattr(pkg, name))


def test_pipeline_step_import_path_is_stable():
    from spreadsheet_handling.domain.transformations.fk_helpers import (
        drop_helpers,
        enrich_helpers,
    )

    assert enrich_helpers.__name__ == "enrich_helpers"
    assert drop_helpers.__name__ == "drop_helpers"
