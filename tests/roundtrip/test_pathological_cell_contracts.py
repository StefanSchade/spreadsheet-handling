"""Pathological-cell contracts over the full canonical -> workbook -> canonical cycle.

Assert defined behavior when a cell carries non-domain content: empty FK
source values, unresolved FK references, NaN-valued numeric cells,
spreadsheet error tokens (``#NAME?``, ``#N/A``, ``#REF!``), etc.

Unresolved FK-helper values: this module covers two distinct, separately
tracked problems under `BUG-UNRESOLVED-HELPER-VALUE-NAN-SEMANTICS-P4A`:

* the *carrier* problem -- an unresolved helper's pandas missing-value
  carrier used to serialize as backend-divergent, accidental text (the
  literal string ``"nan"`` on ODS, `""` on XLSX only by luck of an
  unrelated OpenPyXL quirk). This is now fixed: both backends
  consistently normalize an unresolved helper to the empty string `""`
  before it ever reaches a renderer. See the passing regression tests
  below.
* the *semantic* problem -- `""` is only a *temporary carrier*
  representation, not an accepted final contract for "unresolved". It is
  known to collide with a legitimately resolved helper whose target value
  is itself an empty string, and the project has not yet decided the final
  representation (null, a reserved sentinel, a structured finding, etc.).
  This remains open; see the xfail sentinel at the bottom of this module.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


pytestmark = [
    pytest.mark.roundtrip,
    pytest.mark.ftr("FTR-ROUNDTRIP-TEST-LAYER-P4A"),
]

_BACKENDS = ("xlsx", "ods")


def _reverse_no_cleanup_pipeline(sheet_path: Path, reimport_dir: Path, kind: str) -> dict:
    """Workbook -> canonical pipeline that deliberately skips helper cleanup.

    Mirrors ``tests/roundtrip/conftest.py``'s ``_reverse_pipeline`` but
    without the ``apply_derived_column_policy`` cleanup step, so the helper
    column stays observable. Parameterized by backend ``kind`` so the same
    shape drives both the XLSX and the ODS no-cleanup reimport path.
    """
    return {
        "io": {
            "input": {"kind": kind, "path": str(sheet_path)},
            "output": {"kind": "json_dir", "path": str(reimport_dir)},
        },
        "pipeline": [
            {
                "step": "apply_workbook_view_sheet_mappings",
                "logical_frames": ["items", "entities"],
            },
        ],
    }


def _reimport_items_row(
    tmp_path: Path,
    *,
    kind: str,
    item_id: str = "ITEM-003",
    entity_id_override: str | None = None,
    entity_name_overrides: dict[str, str] | None = None,
    extra_items: list[dict] | None = None,
) -> dict:
    """Run the minimal-FK-dataset forward/no-cleanup-reverse cycle once.

    Copies the shared fixture, optionally rewrites ``ITEM-003``'s
    ``entity_id`` and/or ``entities.json`` name fields (by id), optionally
    appends extra item rows, then runs the full CLI forward export /
    no-cleanup reverse reimport for the given backend ``kind``. Returns the
    reimported row matching ``item_id``.

    Reuses the maintained ``minimal_fk_workdir`` building blocks
    (``_run_cli``, ``_write_yaml``, the shared fixture directory) rather
    than reinventing pipeline plumbing; only the backend/content
    parameterization is local to this module.
    """
    from tests.roundtrip.conftest import _FIXTURE_ROOT, _forward_pipeline, _run_cli, _write_yaml

    canonical = tmp_path / "canonical"
    canonical.mkdir()
    for src in (_FIXTURE_ROOT / "canonical").glob("*.json"):
        (canonical / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    if entity_id_override is not None:
        items_path = canonical / "items.json"
        items = json.loads(items_path.read_text(encoding="utf-8"))
        items = [
            {**row, "entity_id": entity_id_override} if row.get("id") == "ITEM-003" else row
            for row in items
        ]
        if extra_items:
            items = items + list(extra_items)
        items_path.write_text(json.dumps(items, indent=2), encoding="utf-8")
    elif extra_items:
        items_path = canonical / "items.json"
        items = json.loads(items_path.read_text(encoding="utf-8"))
        items = items + list(extra_items)
        items_path.write_text(json.dumps(items, indent=2), encoding="utf-8")

    if entity_name_overrides:
        entities_path = canonical / "entities.json"
        entities = json.loads(entities_path.read_text(encoding="utf-8"))
        entities = [
            {**row, "name": entity_name_overrides[row["id"]]}
            if row.get("id") in entity_name_overrides
            else row
            for row in entities
        ]
        entities_path.write_text(json.dumps(entities, indent=2), encoding="utf-8")

    sheet = tmp_path / f"workbook.{kind}"
    forward_yaml = tmp_path / "forward.yaml"
    _write_yaml(forward_yaml, _forward_pipeline(canonical, sheet, kind=kind))
    assert _run_cli(forward_yaml) == 0

    reimport = tmp_path / "reimport"
    reverse_yaml = tmp_path / "reverse.yaml"
    _write_yaml(reverse_yaml, _reverse_no_cleanup_pipeline(sheet, reimport, kind))
    assert _run_cli(reverse_yaml) == 0

    items_out = json.loads((reimport / "items.json").read_text(encoding="utf-8"))
    row = next((r for r in items_out if r.get("id") == item_id), None)
    assert row is not None, f"fixture invariant: reimported items.json must contain {item_id!r}"
    return row


# ---------------------------------------------------------------------------
# Fixed: the backend-divergent carrier defect.
#
# Before the fix, an unresolved FK-helper lookup produced Python `None`,
# which pandas silently coerced into a real `float('nan')` carrier. XLSX's
# OpenPyXL writer accidentally dropped that NaN to a blank cell on save,
# while the ODS renderer's `value in (None, "")` emptiness check is
# NaN-blind (`nan != nan`) and fell through to the numeric branch, writing
# the literal text "nan". `apply_fk_helpers` (core/fk.py) now supplies an
# explicit `""` default for an unresolved *lookup miss*, so a lookup miss
# no longer introduces a pandas missing carrier, and neither renderer sees
# a NaN to mishandle for that row. A successful lookup still returns its
# stored target payload verbatim -- if that payload is itself a missing
# carrier, the helper column can still carry one for that row; that case
# is outside this fix (see test_fk_edge_cases.py's
# TestMissingLabelField::test_missing_label_field_results_in_none_helper).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", _BACKENDS)
def test_unresolved_fk_helper_carrier_is_backend_consistent(kind, tmp_path) -> None:
    """A non-empty, unresolvable FK reference must not corrupt to "nan".

    ``ITEM-003`` is changed to reference ``ENT-MISSING`` before export: a
    lookup was requested, but the key cannot be resolved. Regression guard
    for the ODS literal-`"nan"` corruption and the XLSX/ODS divergence; both
    backends must produce the same, non-`"nan"` carrier value.
    """
    row = _reimport_items_row(tmp_path, kind=kind, entity_id_override="ENT-MISSING")

    helper_column = "_entities_name"
    assert helper_column in row, f"no-cleanup reimport must keep {helper_column!r} observable"
    assert row[helper_column] != "nan", (
        f"unresolved helper {helper_column!r} must not serialize as the literal "
        f"string 'nan' on backend {kind!r}; got {row[helper_column]!r}"
    )
    # Current (temporary) carrier behavior, not the final semantic contract --
    # see the xfail sentinel below for the still-open representation question.
    assert row[helper_column] == "", (
        f"unresolved helper {helper_column!r} should carry the current normalized "
        f"empty-string representation on backend {kind!r}; got {row[helper_column]!r}"
    )


@pytest.mark.parametrize("kind", _BACKENDS)
def test_missing_fk_source_helper_carrier_is_backend_consistent(kind, tmp_path) -> None:
    """An empty FK source key must not corrupt to "nan" either.

    Historical reproduction shape (`home_place_id: ""`): the source FK
    column itself is empty, distinct from a non-empty-but-unresolvable
    reference (covered separately above -- the two must not be conflated).
    """
    row = _reimport_items_row(tmp_path, kind=kind, entity_id_override="")

    helper_column = "_entities_name"
    assert helper_column in row
    assert row[helper_column] != "nan", (
        f"empty-source helper {helper_column!r} must not serialize as the literal "
        f"string 'nan' on backend {kind!r}; got {row[helper_column]!r}"
    )
    assert row[helper_column] == "", (
        f"empty-source helper {helper_column!r} should carry the current normalized "
        f"empty-string representation on backend {kind!r}; got {row[helper_column]!r}"
    )


@pytest.mark.parametrize("kind", _BACKENDS)
def test_literal_domain_nan_helper_value_survives_roundtrip(kind, tmp_path) -> None:
    """A legitimate resolved helper value that is literally "nan" must stay "nan".

    The fix must detect the missing *carrier*, not censor the spelling
    "nan": a real domain string equal to "nan" is a dict hit (a successful
    FK resolution), never the unresolved-lookup default, and must round-trip
    unchanged on both backends.
    """
    row = _reimport_items_row(
        tmp_path,
        kind=kind,
        entity_id_override="ENT-001",
        entity_name_overrides={"ENT-001": "nan"},
    )

    helper_column = "_entities_name"
    assert row[helper_column] == "nan", (
        f"resolved helper {helper_column!r} with legitimate target value 'nan' must "
        f"survive roundtrip unchanged on backend {kind!r}; got {row[helper_column]!r}"
    )


@pytest.mark.parametrize("kind", _BACKENDS)
def test_legitimate_empty_helper_value_survives_roundtrip(kind, tmp_path) -> None:
    """A legitimate resolved helper value that is an empty string stays "".

    Not every "" is unresolved: a successful FK resolution whose target
    field happens to be a legitimate empty string is a dict hit, not a
    lookup miss, and must round-trip as "" on both backends. (This value is
    currently indistinguishable from the unresolved-carrier case -- that
    collision is the still-open semantic question the xfail sentinel below
    tracks; this test only guards that the *resolved* path keeps returning
    the real dict value rather than regressing to something else.)
    """
    row = _reimport_items_row(
        tmp_path,
        kind=kind,
        entity_id_override="ENT-001",
        entity_name_overrides={"ENT-001": ""},
    )

    helper_column = "_entities_name"
    assert row[helper_column] == "", (
        f"resolved helper {helper_column!r} with legitimate empty target value must "
        f"survive roundtrip as '' on backend {kind!r}; got {row[helper_column]!r}"
    )


# ---------------------------------------------------------------------------
# Still open: the unresolved-reference semantic contract.
#
# Fixing the carrier defect above makes the *current* representation of an
# unresolved helper value a consistent "" on both backends -- but "" is only
# accepted as temporary carrier behavior, not as the final framework
# contract. It is known to collide with a legitimately resolved helper whose
# target value is itself an empty string: the two cases are indistinguishable
# in canonical JSON today. That representation decision remains open in
# BUG-UNRESOLVED-HELPER-VALUE-NAN-SEMANTICS-P4A.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="BUG-UNRESOLVED-HELPER-VALUE-NAN-SEMANTICS-P4A: the framework has "
    "fixed the backend-divergent carrier defect (an unresolved helper no "
    "longer corrupts to the literal string 'nan' on any backend), but has "
    "not yet decided the final unresolved-reference representation. '' is "
    "only the current normalized carrier value, and it is not distinguishable "
    "from a legitimately resolved helper whose target value is itself an "
    "empty string. The final representation may be null, a structured "
    "finding, a reserved sentinel token, or another documented shape once "
    "that contract decision lands.",
    strict=False,
)
def test_unresolved_helper_value_distinguishable_from_legitimate_empty_string(tmp_path) -> None:
    """An unresolved helper and a legitimately-empty resolved helper collide.

    ``ITEM-003`` references the unresolvable ``ENT-MISSING``; a new
    ``ITEM-004`` resolves successfully to ``ENT-003``, whose ``name`` is
    legitimately the empty string. Both currently reimport with the same
    ``""`` helper value -- the still-open semantic question this sentinel
    tracks, distinct from the now-fixed backend-corruption defect covered by
    the passing tests above.
    """
    from tests.roundtrip.conftest import _FIXTURE_ROOT, _forward_pipeline, _run_cli, _write_yaml

    canonical = tmp_path / "canonical"
    canonical.mkdir()
    for src in (_FIXTURE_ROOT / "canonical").glob("*.json"):
        (canonical / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    items_path = canonical / "items.json"
    items = json.loads(items_path.read_text(encoding="utf-8"))
    items = [
        {**row, "entity_id": "ENT-MISSING"} if row.get("id") == "ITEM-003" else row
        for row in items
    ]
    items.append({"id": "ITEM-004", "name": "Fourth", "entity_id": "ENT-003"})
    items_path.write_text(json.dumps(items, indent=2), encoding="utf-8")

    entities_path = canonical / "entities.json"
    entities = json.loads(entities_path.read_text(encoding="utf-8"))
    entities.append({"id": "ENT-003", "name": ""})
    entities_path.write_text(json.dumps(entities, indent=2), encoding="utf-8")

    sheet = tmp_path / "workbook.xlsx"
    forward_yaml = tmp_path / "forward.yaml"
    _write_yaml(forward_yaml, _forward_pipeline(canonical, sheet))
    assert _run_cli(forward_yaml) == 0

    reimport = tmp_path / "reimport"
    reverse_yaml = tmp_path / "reverse.yaml"
    _write_yaml(reverse_yaml, _reverse_no_cleanup_pipeline(sheet, reimport, "xlsx"))
    assert _run_cli(reverse_yaml) == 0

    items_out = json.loads((reimport / "items.json").read_text(encoding="utf-8"))
    unresolved = next(r for r in items_out if r.get("id") == "ITEM-003")
    resolved_empty = next(r for r in items_out if r.get("id") == "ITEM-004")

    helper_column = "_entities_name"
    assert unresolved[helper_column] != resolved_empty[helper_column], (
        "an unresolved FK reference and a legitimately resolved empty-string "
        f"helper value must remain distinguishable; both reimported as "
        f"{unresolved[helper_column]!r}"
    )
