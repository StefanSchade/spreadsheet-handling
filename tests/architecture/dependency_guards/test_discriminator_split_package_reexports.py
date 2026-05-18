"""Guard: the discriminator_split package preserves its public + registry paths.

FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-DISCRIMINATOR-P5 split the single
``discriminator_split`` module into a package. The pipeline registry (colon
``module:function`` targets), ``meta_registry.yaml`` producer/consumer dotted
references, and tests all depend on ``split_by_discriminator`` /
``merge_by_discriminator`` resolving through ``discriminator_split/__init__.py``
regardless of the internal file layout. Unlike the FK split, discriminator is
registered via ``target=`` (a colon target), so this guard also exercises the
``importlib`` + ``getattr`` colon-target resolution path. It fails fast if a
future internal move forgets to re-export one of the two public functions.
"""

from __future__ import annotations

import importlib

import pytest

from spreadsheet_handling.pipeline.registry import resolve_registration
from spreadsheet_handling.pipeline.types import StepRegistration

pytestmark = pytest.mark.ftr("FTR-DOMAIN-TRANSFORMATION-MODULE-SPLIT-DISCRIMINATOR-P5")

_PACKAGE = "spreadsheet_handling.domain.transformations.discriminator_split"

# The only names that are part of the public/registry/meta-registry contract.
_REQUIRED_SYMBOLS = ("split_by_discriminator", "merge_by_discriminator")


def test_public_symbols_resolve_through_package_root():
    pkg = importlib.import_module(_PACKAGE)
    for name in _REQUIRED_SYMBOLS:
        assert hasattr(pkg, name), (
            f"{_PACKAGE}.{name} must stay accessible via the package __init__; "
            f"it is part of the public/registry/meta-registry contract."
        )
        assert callable(getattr(pkg, name))
        assert getattr(pkg, name).__name__ == name


def test_only_public_surface_is_re_exported():
    pkg = importlib.import_module(_PACKAGE)
    assert sorted(getattr(pkg, "__all__", [])) == sorted(_REQUIRED_SYMBOLS)


def test_registry_step_ids_resolve_to_package_root_targets():
    for name in _REQUIRED_SYMBOLS:
        registration = resolve_registration(name)
        assert isinstance(registration, StepRegistration)
        assert registration.target == f"{_PACKAGE}:{name}"


def test_colon_target_resolution_imports_through_package_root():
    """The colon ``module:function`` form must import + getattr cleanly."""
    for name in _REQUIRED_SYMBOLS:
        registration = resolve_registration(f"{_PACKAGE}:{name}")
        assert isinstance(registration, StepRegistration)
        resolved = registration.factory
        assert callable(resolved)
        assert resolved.__name__ == name
        mod = importlib.import_module(_PACKAGE)
        assert resolved is getattr(mod, name)
