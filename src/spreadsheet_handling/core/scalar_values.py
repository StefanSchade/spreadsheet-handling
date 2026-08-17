"""Minimal internal scalar-value contract (Phase D, domain hardening roadmap).

This module is the runtime slice of `FTR-MINIMAL-INTERNAL-VALUE-MODEL-P4A`
(String/Boolean/Number/Missing, Slice 1) and, since D-T1, also of
`FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A` (Date/DateTime classification). It
answers one narrow *value-model* question -- "is this payload representable
in the framework's normal internal scalar space?" -- and does not itself
answer the *ingress-policy* question ("what happens when it is not?") or the
*sink-capability* question ("may this pipeline emit it as a formula?"). The
ingress-policy question is Trusted Ingress's job (Phase E, complete: it calls
this classifier at the framework-managed entry points and rejects an
unsupported value before ordinary Domain code sees it -- see
`docs/technical_model/ch06_architectural_layers/architectural_layers.adoc`,
"Establishing and Re-establishing the Domain Scalar Language"); the
sink-capability question remains an existing, separate, sink-local concern
this module does not address either way.

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
* *Date* -- native `datetime.date`. Added by D-T1
  (`FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A`). Checked *after* DateTime, since
  `datetime.datetime` (and `pandas.Timestamp`) subclass `datetime.date` --
  the same subclass-ordering hazard Boolean-before-Number already solves for
  `bool`/`int`, applied to a second pair.
* *DateTime* -- native `datetime.datetime` (and `pandas.Timestamp`,
  `numpy.datetime64`, which do not subclass `datetime.datetime`/`date` but
  classify into it without being narrowed to it -- the same "classify
  without normalizing" contract Number/Boolean already use for their own
  NumPy variants). Every non-`NaT` `numpy.datetime64` value classifies as
  DateTime uniformly, regardless of unit/precision -- day-precision storage
  is bit-identically ambiguous between "authored as a date" and "a datetime
  truncated to day granularity", so no unit-based Date-vs-DateTime heuristic
  is used. Timezone-aware `datetime.datetime`/`Timestamp` classifies as
  DateTime, the same as naive -- `tzinfo` is never stripped, an aware value
  is never silently converted to naive, and a naive value is never assumed
  to be UTC; this settles category membership only, not a timezone
  canonicalization policy (deferred to a future boundary/consumer).

Explicitly out of this vocabulary, on purpose, not by omission:

* `datetime.time` -- deferred (`UnsupportedScalarError`). No maintained
  producer or consumer of a bare `time` value exists, and neither
  `yaml.safe_dump` nor `json.dumps` can even serialize one -- strictly more
  expensive to support than Date/DateTime, not merely equally deferred.
* `datetime.timedelta` / `pandas.Timedelta` / `numpy.timedelta64` (Duration)
  -- rejected (`UnsupportedScalarError`), uniformly, `NaT`-valued or not.
  `numpy.timedelta64` requires an explicit exclusion (both here and in
  `is_missing_carrier`) because it subclasses `numpy.integer`, which would
  otherwise silently accept it as Number
  (`BUG-NUMPY-TIMEDELTA64-NUMBER-MISCLASSIFICATION-P4A`); Duration is
  conceptually distinct from Date/Time even though NumPy implements both
  under one shared `np.generic` ancestor, and is not a category candidate
  this module supports, deferred or otherwise.
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
ingress point -- it classifies, it does not enforce. Trusted Ingress (Phase
E, complete) is the framework code that calls this classifier at the
framework-managed entry points to establish and re-establish
Ingress-Conformant Domain Payload; see
`docs/technical_model/ch06_architectural_layers/architectural_layers.adoc`,
"Establishing and Re-establishing the Domain Scalar Language". The five
historical local `is_missing_carrier`-shaped predicates predating this module
were not retrofitted to import this one merely by this module's own
introduction (see the FTR's own D1 acceptance note); this module's role
remains to make the predicate available at a location every caller can reach
without crossing an unwanted `io_backends` -> `domain` dependency.
"""
from __future__ import annotations

import datetime
from typing import Any, Literal, TypeAlias

import numpy as np
import pandas as pd

ScalarValue: TypeAlias = (
    str | bool | int | float | datetime.date | datetime.datetime | None
)
"""Candidate native-Python value shape for the MVP scalar vocabulary -- not
the complete accepted carrier domain, and not a canonical normalized
representation. Do not read this alias as "what `scalar_category` narrows an
accepted value down to."

`ScalarCategory` (below) is the actual semantic vocabulary --
String/Boolean/Number/Missing/Date/DateTime. `scalar_category` *classifies* a
value into one of those categories; its accepted carrier domain is broader
than this alias states on its own, because it also accepts carrier variants
named in the module docstring above (`numpy.integer`, `numpy.floating`,
`numpy.bool_`, `numpy.str_`, `pandas.Timestamp`, `numpy.datetime64`) without
narrowing them to a `ScalarValue` member -- a `numpy.int64` classifies as
`"number"` while remaining a `numpy.int64`, not becoming a Python `int`; a
`pandas.Timestamp` classifies as `"datetime"` while remaining a
`pandas.Timestamp`, not becoming a `datetime.datetime`. `datetime.date`/
`datetime.datetime` are included here, consistent with `int`/`float`, because
they are Date/DateTime's own conceptual canonical carriers (D-T1,
`FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A` section 12) -- the same role `int`/
`float` already play for Number; their carrier *variants*
(`pandas.Timestamp`, `numpy.datetime64`) are deliberately not added here, for
the same reason `numpy.int64`/`numpy.float64` are not.

Slice 1 (`FTR-MINIMAL-INTERNAL-VALUE-MODEL-P4A`) does *not* establish a
canonical normalized scalar representation, and D-T1 does not change that
posture. `scalar_category` is pure classification, not conversion (see its
own docstring): it never narrows an accepted value down to this alias's
literal members. No `normalize_scalar()`-shaped primitive exists anywhere in
this module. Producing an actual normalized value from an accepted carrier
(NumPy scalar variants, `pandas.Timestamp`, `numpy.datetime64` included) is a
deliberate non-goal of this module, per Independent Review 001, finding
IVM-REVIEW-F2, and per `FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A` section 12/
DTVM-REVIEW-F2. Trusted Ingress (Phase E, complete) established admission/
classification at the framework-managed entry points, not carrier
normalization; general scalar normalization and canonical carrier
resolution were not part of that work and remain a separate, currently
undecided question, not owned by this module or by any currently accepted,
authorized, or planned phase.

`None` is the most common Missing carrier, but it is not the only one
`is_missing_carrier` recognizes (`""` and the NaN/`pandas.NA`/`NaT`/
`numpy.datetime64('NaT')` family are also accepted carriers) -- Missing is a
recognition predicate over carriers already accepted by `scalar_category`,
not a distinct member of this union. See `is_missing_carrier`.
"""

ScalarCategory: TypeAlias = Literal[
    "string", "boolean", "number", "missing", "date", "datetime"
]
"""The closed scalar-category vocabulary. Error, Integer-vs-Float, Time, and
Duration are deliberately not members -- see the module docstring."""


class UnsupportedScalarError(TypeError):
    """`value` is outside the MVP internal scalar vocabulary.

    The diagnostic deliberately uses constant type detail rather than
    introspecting the rejected value or its runtime type. It never calls
    `repr`, `str`, comparison, hashing, iteration, instance `__class__`, or
    metaclass behavior on the rejected value -- a bounded, safe diagnostic per
    `ADR-DOMAIN-BOUNDARY-ROBUSTNESS`, not an attempt to describe the value's
    content or provide a general same-process sandbox.
    """

    def __init__(self, value: Any) -> None:
        self.value_type_name = "unsupported runtime type"
        super().__init__(
            "unsupported internal scalar value of type "
            f"{self.value_type_name!r}; expected str, bool, int, float, "
            "date, datetime, or a recognized missing carrier"
        )


def _actual_type_is_subclass_of(
    actual_type: type[Any], accepted_types: tuple[type[Any], ...]
) -> bool:
    """Whether the real runtime type descends from an accepted carrier type.

    ``actual_type`` is anchored by the caller with ``type(value)`` so a
    caller-controlled ``value.__class__`` cannot affect membership.
    ``issubclass`` performs the ancestry test without attribute lookup on that
    first-argument type. Its customizable side is the second argument's
    metaclass; every ``accepted_types`` entry here is a fixed built-in,
    ``datetime``, or NumPy carrier type using the standard ``type`` metaclass.
    Thus neither the candidate instance nor its user-controlled metaclass
    participates in proving membership for this bounded family set.
    """
    return issubclass(actual_type, accepted_types)


def is_missing_carrier(value: Any) -> bool:
    """True for a real missing carrier: `None`, `""`, or a NaN/NA/NaT scalar.

    This is *recognition*, not *representation*: it answers whether `value`'s
    current carrier is a missing one; it does not produce or mutate a value.
    A literal string that happens to equal `"nan"` is deliberately not
    recognized as missing -- actual runtime String ancestry is checked before
    `pandas.isna`, matching the semantics of every existing accepted
    implementation of this shape (`domain._cell_primitives._is_empty_cell`,
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

    `numpy.datetime64` is given its own explicit branch, ahead of the
    `np.generic` bounded dispatch, using `numpy.isnat` -- a bounded,
    temporal-specific NumPy operation, not the broad `pandas.isna` dispatch
    the other `np.generic` scalars share. Before D-T1
    (`FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A` section 6, closing the
    remaining half of Independent Review 001's finding IVM-REVIEW-F7), a
    `numpy.datetime64('NaT')` value reached "missing" only as an accidental
    side effect of the generic `np.generic` bucket below, before Date/Time
    was a supported category at all. Now that DateTime is a supported
    category (see `scalar_category`), this is its own owned, explicit rule:
    `numpy.datetime64('NaT')` is Missing; every other `numpy.datetime64`
    value is not.
    """
    actual_type = type(value)
    if value is None:
        return True
    if _actual_type_is_subclass_of(actual_type, (str,)):
        return value == ""
    if value is pd.NA or value is pd.NaT:
        return True
    if _actual_type_is_subclass_of(actual_type, (np.timedelta64,)):
        return False
    if _actual_type_is_subclass_of(actual_type, (np.datetime64,)):
        return bool(np.isnat(value))
    if _actual_type_is_subclass_of(actual_type, (int, float, np.generic)):
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
    vocabulary -- including `datetime.time`, `datetime.timedelta`/
    `pandas.Timedelta`/`numpy.timedelta64`, `FormulaSpec` instances, and
    arbitrary Python objects -- rather than silently widening a category to
    fit them.

    Classification order matters and is deliberate:

    1. `is_missing_carrier` first, so every accepted missing carrier
       (`None`, `""`, NaN/`pandas.NA`/`NaT`/`numpy.datetime64('NaT')`,
       including a NaN-valued `float` or `numpy.floating`) classifies as
       `"missing"` before any type check below could otherwise misclassify
       it as `"number"` or `"datetime"`.
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
    4. DateTime before Date, because `datetime.datetime` subclasses
       `datetime.date`, and `pandas.Timestamp` subclasses `datetime.datetime`
       -- the identical subclass-ordering hazard Boolean-before-Number
       already solves, applied to a second pair
       (`FTR-DATE-TIME-INTERNAL-VALUE-MODEL-P4A` section 8, D-T1).
       `numpy.datetime64` is checked alongside DateTime; it is unrelated to
       `datetime.date`/`datetime.datetime` by inheritance, so its own
       ordering relative to them does not matter, only that its `NaT` form
       was already routed to `"missing"` by step 1 above.
    """
    actual_type = type(value)
    if is_missing_carrier(value):
        return "missing"
    if _actual_type_is_subclass_of(actual_type, (bool, np.bool_)):
        return "boolean"
    if _actual_type_is_subclass_of(actual_type, (str,)):
        return "string"
    if _actual_type_is_subclass_of(actual_type, (np.timedelta64,)):
        raise UnsupportedScalarError(value)
    if _actual_type_is_subclass_of(
        actual_type, (int, float, np.integer, np.floating)
    ):
        return "number"
    if _actual_type_is_subclass_of(actual_type, (np.datetime64, datetime.datetime)):
        return "datetime"
    if _actual_type_is_subclass_of(actual_type, (datetime.date,)):
        return "date"
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
