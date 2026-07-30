"""Shared ownership checks for configuration-addressed dotted callables."""

from __future__ import annotations

import importlib
from typing import Any, Callable

_FRAMEWORK_INTERNAL_CONFIGURATION_NAMESPACES: tuple[str, ...] = (
    "spreadsheet_handling.domain.ingress",
)


def ensure_configuration_addressable(reference: str) -> None:
    """Reject framework-owned callables from maintained configuration paths.

    ``reference`` may use ``module:function`` or ``module.function`` form.
    """
    module_path, _ = _split_reference(reference)
    _ensure_module_addressable(reference, module_path)


def _ensure_module_addressable(reference: str, module_path: str) -> None:
    for namespace in _FRAMEWORK_INTERNAL_CONFIGURATION_NAMESPACES:
        if module_path == namespace or module_path.startswith(f"{namespace}."):
            raise ValueError(
                f"Dotted callable {reference!r} is framework-internal and not "
                "configuration/plugin-addressable"
            )


def resolve_configuration_callable(reference: str) -> Callable[..., Any]:
    """Resolve a configuration-derived callable through the ownership boundary."""
    module_path, attribute = _split_reference(reference)
    _ensure_module_addressable(reference, module_path)
    target = getattr(importlib.import_module(module_path), attribute)
    if not callable(target):
        raise TypeError(f"Not callable: {reference}")
    return target


def _split_reference(reference: str) -> tuple[str, str]:
    if not isinstance(reference, str):
        raise TypeError("Dotted callable reference must be a string")
    if not reference or any(character.isspace() for character in reference):
        raise ValueError(
            "Dotted callable reference must use module:function or module.function form"
        )

    if ":" in reference:
        if reference.count(":") != 1:
            raise ValueError(
                "Dotted callable reference must contain at most one ':' separator"
            )
        module_path, attribute = reference.split(":", 1)
    else:
        module_path, separator, attribute = reference.rpartition(".")
        if not separator:
            module_path = ""

    if not module_path or not attribute or module_path.endswith("."):
        raise ValueError(
            "Dotted callable reference must use module:function or module.function form"
        )
    return module_path, attribute


__all__ = ["ensure_configuration_addressable", "resolve_configuration_callable"]
