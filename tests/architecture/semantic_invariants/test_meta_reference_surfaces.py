"""Guard: schema-maintenance reference policies match their registry declarations.

Review 005 Slice 1 (rename_column metadata reference propagation): the
frozensets in ``domain/schema_maintenance/meta_refs.py`` decide which ``_meta``
roots are maintained, blocked, or ignored during column schema maintenance.
``registries/domain_contracts/canonical/meta_reference_surfaces.json`` declares
those policies. This module fails when either side changes without the other,
so the declaration cannot silently drift from the behavior
(GAP-META-REF-DECLARATIONS-IN-CODE).
"""

from __future__ import annotations

import json
from pathlib import Path

from spreadsheet_handling.domain.schema_maintenance import meta_refs

REPO_ROOT = Path(__file__).resolve().parents[3]
SURFACES_PATH = (
    REPO_ROOT / "registries" / "domain_contracts" / "canonical" / "meta_reference_surfaces.json"
)

DUNDER_PREFIX_ROOT = "__*"
CATCH_ALL_ROOT = "*"


def _surfaces() -> list[dict]:
    return json.loads(SURFACES_PATH.read_text(encoding="utf-8"))


def _roots_with_role(rows: list[dict], role: str) -> set[str]:
    return {row["meta_root"] for row in rows if row["maintenance_role"] == role}


def test_supported_roots_match_registry_declaration() -> None:
    assert _roots_with_role(_surfaces(), "supported") == set(meta_refs.SUPPORTED_ROOT_NAMES)


def test_blocked_roots_match_registry_declaration() -> None:
    declared = _roots_with_role(_surfaces(), "blocked") - {CATCH_ALL_ROOT}
    assert declared == set(meta_refs.BLOCKED_ROOTS_BY_NAME)


def test_ignored_roots_match_registry_declaration() -> None:
    declared = _roots_with_role(_surfaces(), "ignored")
    assert DUNDER_PREFIX_ROOT in declared, (
        "the __-prefix skip rule (meta_refs.is_out_of_scope_root) must be a "
        "declared ignored surface"
    )
    assert declared - {DUNDER_PREFIX_ROOT} == set(meta_refs.OUT_OF_SCOPE_ROOT_NAMES)


def test_derived_is_the_only_reported_root() -> None:
    assert _roots_with_role(_surfaces(), "reported") == {"derived"}


def test_unknown_root_default_is_declared_blocking() -> None:
    rows = [row for row in _surfaces() if row["meta_root"] == CATCH_ALL_ROOT]
    assert len(rows) == 1, "exactly one catch-all surface row is expected"
    row = rows[0]
    assert row["maintenance_role"] == "blocked"
    assert row["rename_column_policy"] == "block"
    assert row["drop_column_policy"] == "block"


def test_update_policies_anchor_to_meta_update_code() -> None:
    for row in _surfaces():
        if row["rename_column_policy"] == "update":
            assert "meta_update.py" in row["evidence"], row["id"]


def test_surface_evidence_paths_exist() -> None:
    missing: list[str] = []
    for row in _surfaces():
        for chunk in row["evidence"].split(";"):
            reference = chunk.strip().split(":", 1)[0]
            if reference.startswith(("src/", "tests/")) and not (REPO_ROOT / reference).exists():
                missing.append(f"{row['id']}: {reference}")
    assert not missing, missing


# ---------------------------------------------------------------------------
# Meta Registry Bridge (Review 005 Slice 1d): surface rows join to
# registries/meta_registry.yaml entry names. The YAML stays the source of
# truth for meta inventory/ownership; it is parsed directly here - no JSON
# mirror exists or may be introduced to make this cheaper.
# ---------------------------------------------------------------------------

import yaml  # noqa: E402

META_REGISTRY_PATH = REPO_ROOT / "registries" / "meta_registry.yaml"

PATTERN_ROOTS = {CATCH_ALL_ROOT, DUNDER_PREFIX_ROOT}

# Non-pattern rows may stay unjoined only when their notes carry this marker,
# stating that the root is intentionally not (yet) in the meta registry.
UNINVENTORIED_MARKER = "uninventoried"


def _meta_registry_entry_names() -> set[str]:
    registry = yaml.safe_load(META_REGISTRY_PATH.read_text(encoding="utf-8"))
    return {entry["name"] for entry in registry["entries"]}


def test_bridge_entries_resolve_in_meta_registry() -> None:
    entry_names = _meta_registry_entry_names()
    unresolved = [
        f"{row['id']}: {row['meta_registry_entry']!r}"
        for row in _surfaces()
        if row["meta_registry_entry"] and row["meta_registry_entry"] not in entry_names
    ]
    assert not unresolved, unresolved


def test_non_pattern_rows_are_joined_or_explicitly_uninventoried() -> None:
    offenders = [
        row["id"]
        for row in _surfaces()
        if row["meta_root"] not in PATTERN_ROOTS
        and not row["meta_registry_entry"]
        and UNINVENTORIED_MARKER not in row["notes"]
    ]
    assert not offenders, (
        "non-pattern surface rows must join a meta_registry.yaml entry or "
        f"carry an explicit '{UNINVENTORIED_MARKER}' note: {offenders}"
    )


def test_pattern_rows_stay_unjoined() -> None:
    # `*` and `__*` describe rule surfaces, not one inventory entry; a join
    # there would misattribute several YAML entries to a single row.
    for row in _surfaces():
        if row["meta_root"] in PATTERN_ROOTS:
            assert row["meta_registry_entry"] == "", row["id"]


def test_report_meta_registry_roots_without_surface_row() -> None:
    """Visibility only - never fails on coverage (Slice 1d, optional item).

    Prints meta-registry entries whose name is not referenced by any surface
    row so a reviewer can see which inventoried meta has no declared
    schema-maintenance policy. Forced coverage is explicitly not a goal.
    """
    joined = {row["meta_registry_entry"] for row in _surfaces() if row["meta_registry_entry"]}
    uncovered = sorted(_meta_registry_entry_names() - joined)
    print(
        f"meta_registry entries without a meta_reference_surfaces join ({len(uncovered)}): "
        + ", ".join(uncovered)
    )
    assert isinstance(uncovered, list)
