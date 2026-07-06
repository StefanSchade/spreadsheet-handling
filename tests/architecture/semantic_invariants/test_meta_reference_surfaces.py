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
