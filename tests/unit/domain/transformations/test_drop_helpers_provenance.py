"""FTR-FK-HELPER-PROVENANCE-CLEANUP: drop_helpers prefers metadata over prefix.

FTR-FK-HELPERS-POLICY-DRIVEN-PRIMITIVES-P5 removed the prefix fallback that
previously served as the no-policy path; ``remove_fk_helpers`` now requires
either derived helper provenance or v2 relation policy. Tests in this module
seed v2 policy via ``infer_fk_relations`` before invoking ``add_fk_helpers``.
"""
from __future__ import annotations

import pytest
import pandas as pd

from spreadsheet_handling.domain.fk_relations import infer_fk_relations
from spreadsheet_handling.domain.helper_policies import configure_fk_helpers
from spreadsheet_handling.domain.transformations.enrich_lookup import enrich_lookup
from spreadsheet_handling.pipeline.steps import make_apply_fks_step, make_drop_helpers_step

pytestmark = pytest.mark.ftr("FTR-FK-HELPER-PROVENANCE-CLEANUP")

DEFAULTS = {"id_field": "id", "label_field": "name", "helper_prefix": "_"}


def _enriched_frames(*, defaults=None):
    """Apply FK helpers and return frames with provenance."""
    defaults = defaults or DEFAULTS
    frames = infer_fk_relations({
        "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
        "B": pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]}),
    })
    step = make_apply_fks_step(defaults=defaults)
    return step.fn(frames)


class TestDropHelpersWithProvenance:

    def test_removes_helper_columns_via_provenance(self):
        enriched = _enriched_frames()
        step = make_drop_helpers_step(prefix="_")
        out = step.fn(enriched)

        cols_a = list(out["A"].columns)
        assert all("_B_name" not in str(c) for c in cols_a)
        assert "id" in [c[0] if isinstance(c, tuple) else c for c in cols_a]

    def test_provenance_cleaned_up_after_drop(self):
        enriched = _enriched_frames()
        step = make_drop_helpers_step(prefix="_")
        out = step.fn(enriched)

        meta = out.get("_meta", {})
        derived = meta.get("derived", {})
        sheets = derived.get("sheets", {})
        for sheet_info in sheets.values():
            assert "helper_columns" not in sheet_info

    def test_multiple_helpers_removed_via_provenance(self):
        frames = {
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
            "B": pd.DataFrame(
                {"id": [1, 2], "name": ["alpha", "beta"], "category": ["x", "y"]}
            ),
        }
        configured = configure_fk_helpers(
            frames,
            target="B",
            key="id",
            allowed_helpers=["category", "name"],
            default_helpers=["category", "name"],
        )
        enriched = make_apply_fks_step(defaults=DEFAULTS).fn(configured)
        out = make_drop_helpers_step(prefix="_").fn(enriched)

        cols_a = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        assert "_B_category" not in cols_a
        assert "_B_name" not in cols_a
        assert "id_(B)" in cols_a

    def test_non_helper_underscored_column_kept_with_provenance(self):
        """Provenance-based cleanup only removes listed columns, not all '_' columns."""
        enriched = _enriched_frames()
        enriched["A"][("_custom_field",) + ("",) * 2] = ["x", "y"]

        step = make_drop_helpers_step(prefix="_")
        out = step.fn(enriched)

        cols_a = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        # _B_name removed (in provenance), but _custom_field kept (not in provenance)
        assert "_B_name" not in cols_a
        assert "_custom_field" in cols_a


class TestDropHelpersRequiresPolicy:

    def test_no_policy_and_no_provenance_raises_with_actionable_message(self):
        """Without provenance or v2 policy, drop_helpers fails clearly."""
        frames = {
            "A": pd.DataFrame(
                {"id": [10], "id_(B)": [1], "_B_name": ["alpha"], "_custom": ["z"]}
            ),
            "B": pd.DataFrame({"id": [1], "name": ["alpha"]}),
        }
        step = make_drop_helpers_step(prefix="_")
        with pytest.raises(ValueError, match="infer_fk_relations"):
            step.fn(frames)

    def test_drop_survives_v2_policy_only_column_when_provenance_missing(self):
        """Durable v2 relation policy alone is not deletion authority.

        When only v2 policy is present (no per-sheet transient provenance),
        the declared helper column is left in place: the policy names what
        FK would request, not what FK currently produced on this frame. This
        was previously the post-reimport cleanup path (durable-policy
        fallback); Slice 4 removes that fallback because it permits deleting
        a physically present column -- possibly owned by another producer by
        now (Lookup, or a genuine same-label replacement) -- with no
        truthful evidence FK itself produced it in this run. See accepted
        design ``derived_artifact_deletion_authority_design_2026-08-21.adoc``
        Section F/G.
        """
        frames = infer_fk_relations({
            "A": pd.DataFrame(
                {"id": [10, 20], "id_(B)": [1, 2], "_B_name": ["alpha", "beta"]}
            ),
            "B": pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]}),
        })
        # No derived.sheets provenance was written.
        assert "derived" not in (frames.get("_meta") or {})

        step = make_drop_helpers_step(prefix="_")
        out = step.fn(frames)

        cols_a = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        assert "_B_name" in cols_a
        assert "id_(B)" in cols_a


class TestDropHelpersDeletionAuthority:
    """Slice 4: durable v2 relation policy is never independent deletion
    authority; only truthful, current transient provenance authorizes
    ``drop_helpers`` to delete a helper column. See accepted design
    ``derived_artifact_deletion_authority_design_2026-08-21.adoc`` Section
    F/G and the Slice-3 implementation review's Area 8 confirmatory repro.
    """

    def test_drop_survives_genuine_same_label_replacement_after_decoupled_rebind(self):
        """Slice-3-review Area 8 confirmatory repro, now closed by Slice 4.

        FK truthfully materializes ``_B_name`` on ``A`` and writes matching
        transient provenance. A decoupled ``enrich_lookup(source="C",
        output="A", ...)`` rebind then physically replaces ``A`` with
        caller-owned content that happens to reuse the exact same label
        ``_B_name`` -- Slice 3 already strips FK's now-stale provenance for
        ``A`` as part of that write, so no transient FK provenance survives
        for ``A``. Durable v2 FK relation policy still names ``_B_name`` for
        ``A`` (unaware of the replacement); before Slice 4 that policy alone
        let ``drop_helpers`` delete the caller's replacement column. Slice 4
        must leave it untouched.
        """
        enriched = _enriched_frames()
        assert enriched["_meta"]["derived"]["sheets"]["A"]["helper_columns"]

        frames = dict(enriched)
        frames["C"] = pd.DataFrame({"id": [1, 2], "_B_name": ["caller-x", "caller-y"]})

        rebound = enrich_lookup(
            frames,
            source="C",
            lookup="B",
            output="A",
            on="id",
            helpers=None,
        )
        # Slice 3: the decoupled rebind discards FK's stale record for "A".
        assert "A" not in (rebound.get("_meta", {}).get("derived", {}).get("sheets", {}))
        assert list(rebound["A"]["_B_name"]) == ["caller-x", "caller-y"]

        out = make_drop_helpers_step(prefix="_").fn(rebound)

        cols_a = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        assert "_B_name" in cols_a
        assert list(out["A"]["_B_name"]) == ["caller-x", "caller-y"]

    def test_drop_is_safe_noop_when_provenance_names_absent_column(self):
        """Truthful transient provenance naming a column no longer present
        on the frame is a safe no-op, not an error -- unchanged existing
        behavior, unrelated to the durable-policy-only case above (here
        provenance is still trusted; there simply is nothing left to drop).
        """
        enriched = _enriched_frames()
        frames = dict(enriched)
        frames["A"] = frames["A"].drop(columns=["_B_name"])

        out = make_drop_helpers_step(prefix="_").fn(frames)

        cols_a = [c[0] if isinstance(c, tuple) else c for c in out["A"].columns]
        assert "_B_name" not in cols_a
        assert "id_(B)" in cols_a


class TestDropHelpersRoundtrip:

    def test_apply_then_drop_roundtrip(self):
        """Full apply → drop roundtrip restores original columns."""
        original = infer_fk_relations({
            "A": pd.DataFrame({"id": [10, 20], "id_(B)": [1, 2]}),
            "B": pd.DataFrame({"id": [1, 2], "name": ["alpha", "beta"]}),
        })
        enriched = make_apply_fks_step(defaults=DEFAULTS).fn(original)
        cleaned = make_drop_helpers_step(prefix="_").fn(enriched)

        cols_a = [c[0] if isinstance(c, tuple) else c for c in cleaned["A"].columns]
        assert cols_a == ["id", "id_(B)"]
