"""Minimal internal scalar-value contract (Phase D, domain hardening roadmap).

This module is the runtime slice of `FTR-MINIMAL-INTERNAL-VALUE-MODEL-P4A`. It
answers one narrow *value-model* question -- "is this payload representable
in the framework's normal internal scalar space?" -- and does not answer any
*ingress-policy* question ("what happens when it is not?") or *sink-capability*
question ("may this pipeline emit it as a formula?"). Those remain Phase E
(mandatory trusted ingress) and existing sink-local concerns respectively; see
the FTR's "Handoff to Trusted Ingress" section.

Scope, restated from the FTR (do not re-derive elsewhere; extend the FTR
instead of drifting this docstring out of sync with it):

* *String* -- native `str`. No wrapper. Numeric-, boolean-, date-, and
  formula-looking strings remain plain strings; nothing here parses string
  content to guess a richer type (no heuristic coercion).
* *Boolean* -- native `bool` (and `numpy.bool_`, which does not subclass
  `bool`). Checked before Number, because Python's `bool` is a subclass of
  `int`.
* *Number* -- one category for `int`/`float` (and `numpy.integer`/
  `numpy.floating`). Integer-vs-Float is a bounded MVP deferral, not a
  decision this module makes.
* *Missing* -- not a value or a type; a *recognition* over already-accepted
  carriers (`None`, `""`, and the NaN/`pandas.NA`/`NaT` family, recognized
  through a bounded dispatch -- `pandas.isna` for known numeric/NumPy-scalar
  carriers, identity for the `pandas.NA`/`NaT` singletons -- that never
  invokes `pandas.isna` on an arbitrary unrecognized object; see
  `is_missing_carrier`). `is_missing_carrier` is the shared predicate that
  five independent local implementations had already converged on before
  this module existed (see the FTR's normalization-pattern inventory); this
  is the first shared, importable copy, not a new semantic.
* *Error* -- deferred. No current maintained parser can produce a
  distinguishable spreadsheet error carrier, so there is no reachable input
  to classify; `scalar_category` correctly rejects an error-*looking* string
  as an ordinary String, and there is nothing else to reject it as.

Explicitly out of this vocabulary, on purpose, not by omission:

* `date` / `datetime` / `pandas.Timestamp` -- a real date/time scalar is
  rejected (`UnsupportedScalarError`), never silently coerced to String or
  Number. Date/Time is the expected next Phase-D slice, not this one.
* `datetime.timedelta` / `pandas.Timedelta` / `numpy.timedelta64` (Duration)
  -- rejected (`UnsupportedScalarError`), uniformly, `NaT`-valued or not.
  `numpy.timedelta64` requires an explicit exclusion (both here and in
  `is_missing_carrier`) because it subclasses `numpy.integer`, which would
  otherwise silently accept it as Number
  (`BUG-NUMPY-TIMEDELTA64-NUMBER-MISCLASSIFICATION-P4A`); Duration is not a
  category candidate this module supports, deferred or otherwise.
* `core.formulas.FormulaSpec` (`ListLiteralFormulaSpec`, `LookupFormulaSpec`)
  -- authored backend-neutral output Intent, not a payload scalar. Formula
  is not a category candidate at all, deferred or otherwise; see
  `FTR-FORMULA-INGRESS-ROUNDTRIP-WHITELIST-P5`.
* Structural/trusted carriers (`core.exact_table.ExactTable`,
  `domain.transformations.grouped_xref.matrix.GroupedMatrix`) -- carriers,
  not scalar payload; out of this module's scope by definition.
* Any collection (`list`/`dict`/`set`/`tuple`), callable, module, generator,
  file handle, or other opaque object -- rejected with a type-only
  diagnostic. `UnsupportedScalarError` never calls `repr`, `str`,
  comparison, hashing, or iteration on the rejected value, so a pathological
  object cannot trigger its own special-method behaviour merely by being
  rejected (`ADR-DOMAIN-BOUNDARY-ROBUSTNESS`).

This module does not decide what happens to an unsupported value at any real
ingress point -- it classifies, it does not enforce. No adapter, CLI, or
domain transformation is wired to call it by this slice; that wiring is
explicitly Phase E's job. The five existing local `is_missing_carrier`-shaped
predicates are not retrofitted to import this one by this slice either (see
the FTR's own D1 acceptance note) -- this module only makes the predicate
available at a location every future implementer can reach without crossing
an unwanted `io_backends` -> `domain` dependency.
"""
from __future__ import annotations

from typing import Any, Literal, TypeAlias

import numpy as np
import pandas as pd

ScalarValue: TypeAlias = str | bool | int | float | None
"""Candidate native-Python value shape for the MVP scalar vocabulary -- not
the complete accepted carrier domain, and not a canonical normalized
representation. Do not read this alias as "what `scalar_category` narrows an
accepted value down to."

`ScalarCategory` (below) is the actual Slice-1 semantic vocabulary --
String/Boolean/Number/Missing. `scalar_category` *classifies* a value into
one of those categories; its accepted carrier domain is broader than this
alias states on its own, because it also accepts the NumPy scalar variants
named in the module docstring above (`numpy.integer`, `numpy.floating`,
`numpy.bool_`, `numpy.str_`) without narrowing them to a `ScalarValue`
member -- a `numpy.int64` classifies as `"number"` while remaining a
`numpy.int64`, not becoming a Python `int`.

Slice 1 (`FTR-MINIMAL-INTERNAL-VALUE-MODEL-P4A`) does *not* establish a
canonical normalized scalar representation. `scalar_category` is pure
classification, not conversion (see its own docstring): it never narrows an
accepted value down to this alias's literal members. No
`normalize_scalar()`-shaped primitive exists anywhere in this module.
Producing an actual normalized value from an accepted carrier (NumPy scalar
variants included) remains Phase E's "value normalization and type
resolution" boundary-shape stage (`roadmap_domain_hardening_sequence.adoc`
Phase E) -- a follow-on this slice deliberately does not provide, per
Independent Review 001, finding IVM-REVIEW-F2.

`None` is the most common Missing carrier, but it is not the only one
`is_missing_carrier` recognizes (`""` and the NaN/`pandas.NA`/`NaT` family
are also accepted carriers) -- Missing is a recognition predicate over
carriers already accepted by `scalar_category`, not a distinct member of
this union. See `is_missing_carrier`.
"""

ScalarCategory: TypeAlias = Literal["string", "boolean", "number", "missing"]
"""The MVP's closed scalar-category vocabulary. Error, Integer-vs-Float, and
Date/Time are deliberately not members -- see the module docstring."""


class UnsupportedScalarError(TypeError):
    """`value` is outside the MVP internal scalar vocabulary.

    The diagnostic reports only `type(value).__name__`. It deliberately never
    calls `repr`, `str`, comparison, hashing, or iteration on the rejected
    value -- a bounded, safe diagnostic per `ADR-DOMAIN-BOUNDARY-ROBUSTNESS`,
    not an attempt to describe the value's content.
    """

    def __init__(self, value: Any) -> None:
        self.value_type_name = type(value).__name__
        super().__init__(
            "unsupported internal scalar value of type "
            f"{self.value_type_name!r}; expected str, bool, int, float, or a "
            "recognized missing carrier"
        )


def is_missing_carrier(value: Any) -> bool:
    """True for a real missing carrier: `None`, `""`, or a NaN/NA/NaT scalar.

    This is *recognition*, not *representation*: it answers whether `value`'s
    current carrier is a missing one; it does not produce or mutate a value.
    A literal string that happens to equal `"nan"` is deliberately not
    recognized as missing -- `isinstance(value, str)` is checked before
    `pandas.isna`, matching every existing accepted implementation of this
    shape (`domain._cell_primitives._is_empty_cell`,
    `io_backends.ods.odf_renderer._is_missing_carrier`, and others).

    Bounded, not universally dispatched to `pandas.isna`: calling
    `pandas.isna` on an arbitrary object can invoke that object's own
    `__array__` (NumPy's documented array-conversion protocol) while pandas
    decides whether the object is array-like -- which both runs foreign code
    and can raise an exception of any type, not only `TypeError`/`ValueError`
    (confirmed empirically; see Independent Review 001, finding
    IVM-REVIEW-F1). To stay safe on arbitrary/unsupported objects without
    silently widening the accepted Missing carrier set, `pandas.isna` is only
    ever called on a value already known to be one of the accepted
    scalar-carrier shapes -- `int`, `float` (covers `float("nan")`), or a
    NumPy scalar (`numpy.generic`, covering `numpy.floating`/`numpy.integer`/
    `numpy.bool_` and the rest of the NumPy scalar hierarchy). Any other
    object -- including one implementing `__array__`, a
    `pandas.Series`/`DataFrame`, or any opaque object -- never reaches
    `pandas.isna` at all and is recognized as "not missing" directly, without
    invoking any special method on it. `pandas.NA` and `pandas.NaT` are
    recognized by identity rather than through `pandas.isna`, since both are
    stable singletons (confirmed: `pandas.Timestamp("NaT") is pandas.NaT`,
    `pandas.to_datetime(None) is pandas.NaT`) and identity comparison cannot
    invoke any special method on an unrelated object.

    Safe on arbitrary/unsupported objects: nothing here calls `repr`, `str`,
    `==`, hashing, iteration, or NumPy's `__array__` conversion protocol on a
    value outside the bounded carrier shapes above.

    `numpy.timedelta64` is explicitly excluded from the bounded dispatch
    below, even though it is a `numpy.generic` instance: it subclasses
    `numpy.signedinteger`/`numpy.integer`, so without this exclusion its
    `NaT` form would be recognized as Missing purely as a side effect of the
    broad `np.generic` bucket, exactly the `np.generic`-breadth problem this
    bounded dispatch exists to avoid (see Independent Review 001, finding
    IVM-REVIEW-F7, and `FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A` section 6).
    Duration is not a supported category (see `scalar_category`), so no
    `numpy.timedelta64` value -- `NaT` or not -- is Missing; it is uniformly
    unsupported (`BUG-NUMPY-TIMEDELTA64-NUMBER-MISCLASSIFICATION-P4A`).
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, np.timedelta64):
        return False
    if isinstance(value, (int, float, np.generic)):
        try:
            return bool(pd.isna(value))
        except (TypeError, ValueError):
            return False
    return False


def scalar_category(value: Any) -> ScalarCategory:
    """Classify `value` into the MVP internal scalar vocabulary.

    Pure classification, not conversion: a supported `value` is returned to
    the caller unexamined in content and unchanged in identity by this
    function (it only inspects `type`); nothing here parses string content,
    coerces a numeric-looking string, or unifies missing-carrier
    representation. Raises `UnsupportedScalarError` for anything outside the
    vocabulary -- including dates/datetimes/Timestamps, `FormulaSpec`
    instances, and arbitrary Python objects -- rather than silently widening
    a category to fit them.

    Classification order matters and is deliberate:

    1. `is_missing_carrier` first, so every accepted missing carrier
       (`None`, `""`, NaN/`pandas.NA`/`NaT`, including a NaN-valued `float`
       or `numpy.floating`) classifies as `"missing"` before any type check
       below could otherwise misclassify it as `"number"`.
    2. Boolean before Number, because Python's `bool` is a subclass of
       `int` (and because `numpy.bool_` is checked explicitly, as it does
       not subclass `bool`).
    3. `numpy.timedelta64` before Number, because it subclasses
       `numpy.signedinteger`/`numpy.integer` (unlike `numpy.datetime64`,
       which subclasses neither `np.integer` nor `np.floating`). Duration is
       not a supported category, so every `numpy.timedelta64` value must be
       rejected explicitly rather than silently accepted as an ordinary
       Number stripped of its unit
       (`BUG-NUMPY-TIMEDELTA64-NUMBER-MISCLASSIFICATION-P4A`).
    """
    if is_missing_carrier(value):
        return "missing"
    if isinstance(value, (bool, np.bool_)):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, np.timedelta64):
        raise UnsupportedScalarError(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        return "number"
    raise UnsupportedScalarError(value)


def is_supported_scalar(value: Any) -> bool:
    """True if `scalar_category(value)` would succeed.

    Convenience predicate for a caller that only needs a yes/no answer.
    Never raises: unsupported values return `False`, without triggering
    `repr`/comparison/iteration/NumPy-array-conversion on `value` for the
    check itself -- including an object whose own `__array__` would raise
    (see `is_missing_carrier`'s bounded-dispatch note).
    """
    try:
        scalar_category(value)
    except UnsupportedScalarError:
        return False
    return True
