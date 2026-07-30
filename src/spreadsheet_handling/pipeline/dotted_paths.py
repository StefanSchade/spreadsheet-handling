"""Shared ownership checks for configuration-addressed dotted callables."""

from __future__ import annotations

_FRAMEWORK_INTERNAL_CONFIGURATION_NAMESPACES: tuple[str, ...] = (
    "spreadsheet_handling.domain.ingress",
)


def ensure_configuration_addressable(reference: str) -> None:
    """Reject framework-owned callables from maintained configuration paths.

    ``reference`` may use ``module:function`` or ``module.function`` form.
    This function owns only the framework namespace boundary; importing and
    callable validation remain the responsibility of the calling resolver.
    """
    module_path = _module_path(reference)
    for namespace in _FRAMEWORK_INTERNAL_CONFIGURATION_NAMESPACES:
        if module_path == namespace or module_path.startswith(f"{namespace}."):
            raise ValueError(
                f"Dotted callable {reference!r} is framework-internal and not "
                "configuration/plugin-addressable"
            )


def _module_path(reference: str) -> str:
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
    return module_path


__all__ = ["ensure_configuration_addressable"]
