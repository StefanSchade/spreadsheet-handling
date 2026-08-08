"""Pathological-cell contracts over the full canonical -> workbook -> canonical cycle.

Assert defined behavior when a cell carries non-domain content: empty FK
source values, unresolved FK references, NaN-valued numeric cells,
spreadsheet error tokens (``#NAME?``, ``#N/A``, ``#REF!``), etc.

Unresolved FK-helper values: this module covers two distinct problems under
`BUG-UNRESOLVED-HELPER-VALUE-NAN-SEMANTICS-P4A`, both now resolved:

* the *carrier* problem -- an unresolved helper's pandas missing-value
  carrier used to serialize as backend-divergent, accidental text (the
  literal string ``"nan"`` on ODS, `""` on XLSX only by luck of an
  unrelated OpenPyXL quirk). Fixed: both backends consistently normalize an
  unresolved helper to the empty string `""` before it ever reaches a
  renderer. See the passing regression tests below.
* the *semantic* problem -- whether an unresolved reference must be
  distinguishable from a legitimately resolved empty helper value *at the
  helper-cell level*. Accepted answer (Semantic Contract Review 001,
  ACCEPTED): no. The derived helper cell is presentation only; resolution
  authority is the authoritative source FK reference plus a lookup against
  the current target frame. An unresolved reference and a legitimately
  resolved empty target value may both legitimately display `""` in the
  helper cell while remaining fully distinguishable through the source FK
  column plus `validate_fk_helpers` (or equivalent resolution). See
  `test_unresolved_reference_remains_distinguishable_via_authoritative_resolution`
  below, which proves this on both backends through a real roundtrip. No
  distinct unresolved-value carrier, sentinel, or internal type is
  required.

`BUG-ODS-MISSING-CARRIER-LITERAL-NAN-RENDERING-P4A` closed the separate,
more general residual left open by the fix above: the ODS renderer's
per-cell emptiness check itself was NaN-blind (``value in (None, "")`` is
``False`` for a real ``float('nan')``), so *any* raw pandas/NumPy missing
carrier reaching the renderer -- not only an unresolved FK-helper lookup --
was at risk of the same literal-``"nan"`` corruption. See
`test_csv_dir_blank_cell_carrier_is_backend_consistent` below for the
FK-independent, ordinary-column reproduction (an empty ``csv_dir`` CSV cell
becomes a real pandas NaN with no FK-helper machinery involved at all).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spreadsheet_handling.domain.validations.fk_helpers import validate_fk_helpers
from spreadsheet_handling.io_backends.router import get_loader


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
    # Accepted carrier value (Semantic Contract Review 001): the helper cell
    # is presentation only, so "" is the accepted representation here -- see
    # test_unresolved_reference_remains_distinguishable_via_authoritative_resolution
    # below for how resolution state is nonetheless never actually lost.
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
    byte-identical to the unresolved-carrier case at the helper-cell level --
    accepted as intentional, since the two remain distinguishable through the
    source FK plus resolution, per
    test_unresolved_reference_remains_distinguishable_via_authoritative_resolution
    below; this test only guards that the *resolved* path keeps returning the
    real dict value rather than regressing to something else.)
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
# Accepted semantic contract (Semantic Contract Review 001, ACCEPTED):
# the derived helper cell is presentation only, not resolution authority.
# An unresolved reference and a legitimately resolved empty target value may
# both legitimately display "" in the helper cell -- that is not a defect.
# What must hold is that the two situations remain distinguishable through
# the authoritative source FK reference plus a live resolution check
# (`validate_fk_helpers` / `check_unresolvable_fks`), not through the helper
# cell's spelling. This is proven below on both backends through a real
# export/reimport roundtrip.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", _BACKENDS)
def test_unresolved_reference_remains_distinguishable_via_authoritative_resolution(
    kind, tmp_path
) -> None:
    """Unresolved and resolved-empty stay distinguishable, not via the helper cell.

    ``ITEM-003`` references the unresolvable ``ENT-MISSING``; a new
    ``ITEM-004`` resolves successfully to ``ENT-003``, whose ``name`` is
    legitimately the empty string. Both reimport with the byte-identical
    ``""`` helper value on both backends -- accepted, since the helper cell
    is not the authority. `validate_fk_helpers`, run against the reimported
    frames using only the reimported source FK column and target frame
    (never the helper cell's value), must still correctly and exclusively
    flag ``ENT-MISSING`` as unresolved and must not flag ``ENT-003``.
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

    sheet = tmp_path / f"workbook.{kind}"
    forward_yaml = tmp_path / "forward.yaml"
    _write_yaml(forward_yaml, _forward_pipeline(canonical, sheet, kind=kind))
    assert _run_cli(forward_yaml) == 0

    reimport = tmp_path / "reimport"
    reverse_yaml = tmp_path / "reverse.yaml"
    _write_yaml(reverse_yaml, _reverse_no_cleanup_pipeline(sheet, reimport, kind))
    assert _run_cli(reverse_yaml) == 0

    items_out = json.loads((reimport / "items.json").read_text(encoding="utf-8"))
    unresolved = next(r for r in items_out if r.get("id") == "ITEM-003")
    resolved_empty = next(r for r in items_out if r.get("id") == "ITEM-004")

    helper_column = "_entities_name"
    # Confirm the premise: the helper cell alone gives no signal -- both rows
    # are byte-identical. The test must not, and does not, use this value as
    # the distinguishing signal below.
    assert unresolved[helper_column] == resolved_empty[helper_column] == "", (
        f"fixture premise: both rows must share the identical helper-cell "
        f"value '' on backend {kind!r} for this test to prove anything; got "
        f"unresolved={unresolved[helper_column]!r} "
        f"resolved_empty={resolved_empty[helper_column]!r}"
    )

    # Authoritative resolution: load the reimported frames the same way the
    # pipeline itself does, and ask the maintained FK-helper validation
    # primitive -- not this test -- to recompute resolution state from the
    # reimported source FK column plus the reimported target frame.
    loader = get_loader("json_dir")
    frames = loader(str(reimport))
    findings = validate_fk_helpers(frames, defaults={})

    unresolvable = [f for f in findings if f.category == "unresolvable_fk"]
    assert unresolvable, (
        f"validate_fk_helpers must report the unresolved reference on "
        f"backend {kind!r}; findings were {findings!r}"
    )
    assert any("ENT-MISSING" in f.detail for f in unresolvable), (
        f"the unresolvable_fk finding must name ENT-MISSING on backend "
        f"{kind!r}; got {unresolvable!r}"
    )
    assert not any("ENT-003" in f.detail for f in unresolvable), (
        f"ENT-003 resolves successfully (to a legitimate empty target "
        f"value) and must not be reported as unresolved on backend "
        f"{kind!r}; got {unresolvable!r}"
    )


# ---------------------------------------------------------------------------
# BUG-ODS-MISSING-CARRIER-LITERAL-NAN-RENDERING-P4A -- general, FK-independent
# reproduction: an ordinary csv_dir-sourced column with no FK helpers involved
# at all. `CSVBackend.read_multi` (backing the `csv_dir` loader) calls
# `pd.read_csv(p, header=0, encoding="utf-8")` without `dtype=str` or
# `keep_default_na=False` (unlike the single-file `CSVBackend.read` path), so
# a blank CSV cell becomes a genuine pandas NaN before any FK machinery runs.
# Proves the fix is owned at the general ODS render/carrier boundary, not
# specific to the FK-helper successful-hit case covered elsewhere.
# ---------------------------------------------------------------------------


def _write_csv_dir(path: Path, data: dict[str, list[dict]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, records in data.items():
        columns = list(records[0])
        lines = [",".join(columns)]
        for record in records:
            lines.append(
                ",".join("" if record[c] is None else str(record[c]) for c in columns)
            )
        (path / f"{name}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.parametrize("kind", _BACKENDS)
def test_csv_dir_blank_cell_carrier_is_backend_consistent(kind, tmp_path) -> None:
    """A blank csv_dir cell (real pandas NaN, no FK helpers) must not become "nan".

    Reproduction 2 from BUG-ODS-MISSING-CARRIER-LITERAL-NAN-RENDERING-P4A:
    no `configure_fk_helpers`/`add_fk_helpers` step runs here at all -- the
    NaN carrier comes straight from `csv_dir`'s CSV parsing and reaches the
    renderer through an empty pipeline, proving the defect (and its fix) are
    general to the ODS render boundary rather than FK-helper-specific.
    """
    from tests.roundtrip.conftest import _run_cli, _write_yaml

    csv_dir = tmp_path / "csv_in"
    _write_csv_dir(csv_dir, {"notes": [{"id": "1", "note": None}, {"id": "2", "note": "hello"}]})

    sheet = tmp_path / f"workbook.{kind}"
    forward_yaml = tmp_path / "forward.yaml"
    _write_yaml(
        forward_yaml,
        {
            "io": {
                "input": {"kind": "csv_dir", "path": str(csv_dir)},
                "output": {"kind": kind, "path": str(sheet)},
            },
            "pipeline": [],
        },
    )
    assert _run_cli(forward_yaml) == 0

    reimport = tmp_path / "reimport"
    reverse_yaml = tmp_path / "reverse.yaml"
    _write_yaml(
        reverse_yaml,
        {
            "io": {
                "input": {"kind": kind, "path": str(sheet)},
                "output": {"kind": "json_dir", "path": str(reimport)},
            },
            "pipeline": [],
        },
    )
    assert _run_cli(reverse_yaml) == 0

    rows = json.loads((reimport / "notes.json").read_text(encoding="utf-8"))
    row0 = next(r for r in rows if r.get("id") == "1")
    row1 = next(r for r in rows if r.get("id") == "2")

    assert row0["note"] != "nan", (
        f"blank csv_dir cell must not serialize as the literal string 'nan' on "
        f"backend {kind!r}; got {row0['note']!r}"
    )
    assert row0["note"] == "", (
        f"blank csv_dir cell should reload as an empty string on backend "
        f"{kind!r}; got {row0['note']!r}"
    )
    assert row1["note"] == "hello", "non-empty sibling cell must be unaffected"
