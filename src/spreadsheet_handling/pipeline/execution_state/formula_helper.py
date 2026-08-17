"""Standalone FormulaSpec introduction (FTR section 9, "Standalone FormulaSpec transition").

Only the exact reviewed ``add_lookup_helpers(helper_value_mode="formula")``
invocation may introduce ``LookupFormulaSpec`` roles, and only in its
declared helper output columns (FTR section 12, producer treatment table:
"Exact formula-helper behavior"). No pre-existing, copied, or merely
type-matching value is promoted.

The classifier here recognizes exactly the maintained, statically
determinable configuration shape: an inline symmetric ``key`` or an explicit
asymmetric ``source_key``/``lookup_key`` pair, and an explicit
``helpers={"fields": [...]}`` list. A policy-resolved shape
(``helpers="default"``, or a ``missing``/``helper_value_mode`` value taken
from ``_meta.helper_policies``) is UNCERTIFIED for E4's purposes --
reproducing that policy resolution here would absorb ``enrich_lookup``'s own
family semantics (FTR section 26, "Preserve existing family ownership"),
which E4 must not do. This does not narrow the *architecture*: FTR section 9
requires representing the exact maintained introduction, and the maintained
test/roundtrip fixtures for formula mode use exactly this inline shape (see
``tests/unit/domain/transformations/test_lookup_formula_mode.py``).
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from spreadsheet_handling.domain.transformations.enrich_lookup import enrich_lookup
from spreadsheet_handling.pipeline.types import BoundStep

from .bound_configuration import (
    only_known_keys,
    resolve_trusted_call,
    snapshot_scalar,
    snapshot_string_sequence,
)
from .roles import LookupFormulaSpecRole
from .vocabulary import TransitionEffect, TransitionFootprint, Uncertified

# Descriptive label only, matching BoundStep.config["target"]; the actual
# authenticity proof is `enrich_lookup` object identity via
# `resolve_trusted_call`, not this string.
FORMULA_HELPER_TARGET = "spreadsheet_handling.domain.transformations.enrich_lookup:enrich_lookup"

_KNOWN_OPTION_KEYS = frozenset(
    {
        "source",
        "lookup",
        "output",
        "key",
        "source_key",
        "lookup_key",
        "helpers",
        "missing",
        "helper_value_mode",
    }
)


@dataclass(frozen=True)
class FormulaHelperCertificate:
    """The exact reviewed ``add_lookup_helpers`` formula-mode configuration."""

    source: str
    lookup: str
    output: str
    source_key_column: str
    lookup_key_column: str
    fields: tuple[str, ...]
    missing: str

    def footprint(self) -> TransitionFootprint:
        return TransitionFootprint(
            reads=frozenset({self.source, self.lookup}),
            writes=frozenset({self.output}),
            drops=frozenset(),
        )


def classify_formula_helper_step(step: BoundStep) -> FormulaHelperCertificate | Uncertified:
    """Classify one bound ``add_lookup_helpers`` invocation.

    Resolves the authenticated executable/config pair first (see
    ``bound_configuration.resolve_trusted_call``): a step whose ``config``
    looks exactly like a reviewed invocation but does not structurally
    execute ``enrich_lookup`` (forged, or hand-constructed with an unrelated
    ``fn``) is UNCERTIFIED regardless of its configuration. Configuration is
    then read from ``call.kwargs`` -- the authoritative frozen snapshot from
    which the call materializes fresh invocation-local keyword containers --
    on every classification attempt.
    """
    call = resolve_trusted_call(step, expected_target=enrich_lookup)
    if call is None:
        return Uncertified(reason="unauthenticated_binding")
    config = call.kwargs
    if not only_known_keys(config, known=_KNOWN_OPTION_KEYS):
        return Uncertified(reason="unknown_option", detail="add_lookup_helpers")

    if config.get("helper_value_mode") != "formula":
        return Uncertified(reason="uncovered_configuration", detail="helper_value_mode")

    source = snapshot_scalar(config.get("source"))
    lookup = snapshot_scalar(config.get("lookup"))
    output = snapshot_scalar(config.get("output"))
    if not (_is_nonempty_str(source) and _is_nonempty_str(lookup) and _is_nonempty_str(output)):
        return Uncertified(
            reason="unsupported_configuration_value", detail="source/lookup/output"
        )

    missing = snapshot_scalar(config.get("missing"))
    if missing != "empty":
        # "fail" is rejected by enrich_lookup itself for formula mode; a
        # policy-resolved missing (an absent/None inline value) is not
        # statically determinable from bound configuration alone.
        return Uncertified(reason="uncovered_configuration", detail="missing")

    source_key, lookup_key = _classify_join_keys(config)
    if source_key is None or lookup_key is None:
        return Uncertified(reason="uncovered_configuration", detail="join_key")

    fields = _classify_formula_fields(config.get("helpers"))
    if fields is None or not fields:
        return Uncertified(reason="uncovered_configuration", detail="helpers")

    return FormulaHelperCertificate(
        source=source,
        lookup=lookup,
        output=output,
        source_key_column=source_key,
        lookup_key_column=lookup_key,
        fields=fields,
        missing=missing,
    )


def _is_nonempty_str(value: Any) -> bool:
    return type(value) is str and value != ""


def _classify_join_keys(config: Mapping[str, Any]) -> tuple[str | None, str | None]:
    key = snapshot_scalar(config.get("key"))
    source_key = snapshot_scalar(config.get("source_key"))
    lookup_key = snapshot_scalar(config.get("lookup_key"))
    if _is_nonempty_str(key) and source_key is None and lookup_key is None:
        return key, key
    if _is_nonempty_str(source_key) and _is_nonempty_str(lookup_key) and key is None:
        return source_key, lookup_key
    return None, None


def _classify_formula_fields(helpers: Any) -> tuple[str, ...] | None:
    # A dict-shaped ``helpers`` value is stored inside ``call.kwargs`` as a
    # deep-frozen ``MappingProxyType`` (see
    # ``pipeline.types._freeze_effective_value``), not a plain ``dict``, so
    # both exact types are accepted here.
    if type(helpers) is not dict and type(helpers) is not MappingProxyType:
        return None
    if set(helpers.keys()) != {"fields"}:
        return None
    return snapshot_string_sequence(helpers.get("fields"))


def formula_helper_roles(certificate: FormulaHelperCertificate) -> tuple[LookupFormulaSpecRole, ...]:
    """The exact ``LookupFormulaSpecRole`` set this certificate introduces."""
    return tuple(
        LookupFormulaSpecRole(
            frame=certificate.output,
            column=field,
            source_key_column=certificate.source_key_column,
            lookup_sheet=certificate.lookup,
            lookup_key_column=certificate.lookup_key_column,
            missing=certificate.missing,
            effect=TransitionEffect.INTRODUCE,
        )
        for field in certificate.fields
    )


__all__ = [
    "FORMULA_HELPER_TARGET",
    "FormulaHelperCertificate",
    "classify_formula_helper_step",
    "formula_helper_roles",
]
