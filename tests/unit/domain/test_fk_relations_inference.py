"""Unit tests for the ``infer_fk_relations`` configuration step."""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.fk_relations import (
    SCHEMA_VERSION,
    apply_v2_relations,
    build_v2_relation,
    infer_fk_relations,
)
from spreadsheet_handling.domain.helper_policies import configure_fk_helpers


pytestmark = pytest.mark.ftr("FTR-INFER-FK-RELATIONS-CONFIGURATION-STEP-P5")


def _frames() -> dict:
    return {
        "product": pd.DataFrame(
            {
                "id": ["p1", "p2"],
                "id_(product_manager)": ["m1", "m2"],
            }
        ),
        "product_manager": pd.DataFrame(
            {
                "id": ["m1", "m2"],
                "name": ["Alice", "Bob"],
            }
        ),
    }


def test_infer_fk_relations_writes_v2_relation_for_naming_convention() -> None:
    out = infer_fk_relations(_frames())

    fk_root = out["_meta"]["helper_policies"]["fk"]
    assert fk_root["schema_version"] == SCHEMA_VERSION
    relations = fk_root["relations"]
    assert len(relations) == 1
    relation = relations[0]
    assert relation["source_frame"] == "product"
    assert relation["source_column"] == "id_(product_manager)"
    assert relation["target_frame"] == "product_manager"
    assert relation["target_key"] == "id"
    assert relation["helper_fields"] == ["name"]
    assert relation["helper_columns"] == [
        {"column": "_product_manager_name", "target_field": "name"}
    ]
    assert relation["produced_by"] == {
        "step": "infer_fk_relations",
        "mode": "naming_convention",
    }
    assert relation["helper_prefix"] == "_"


def test_infer_fk_relations_does_not_materialize_helper_columns() -> None:
    out = infer_fk_relations(_frames())

    product_columns = list(out["product"].columns)
    assert "_product_manager_name" not in product_columns


def test_infer_fk_relations_does_not_write_derived_provenance() -> None:
    out = infer_fk_relations(_frames())

    meta = out["_meta"]
    assert "derived" not in meta or "sheets" not in (meta.get("derived") or {})


def test_infer_fk_relations_orders_relations_deterministically() -> None:
    frames = {
        "product_manager": pd.DataFrame({"id": ["m1"], "name": ["Alice"]}),
        "products": pd.DataFrame({"id": ["pr1"], "name": ["Widget"]}),
        # Two source frames, two FK columns, intentionally not alphabetic order.
        "z_order": pd.DataFrame({"id_(product_manager)": ["m1"]}),
        "a_order": pd.DataFrame(
            {
                "id_(product_manager)": ["m1"],
                "id_(products)": ["pr1"],
            }
        ),
    }
    out = infer_fk_relations(frames)
    relations = out["_meta"]["helper_policies"]["fk"]["relations"]
    keys = [(r["source_frame"], r["source_column"]) for r in relations]
    assert keys == sorted(keys)


def test_infer_fk_relations_raises_on_missing_target_when_configured() -> None:
    frames = {
        "product": pd.DataFrame({"id_(missing_target)": ["x"]}),
    }
    with pytest.raises(ValueError, match="missing_target"):
        infer_fk_relations(frames)


def test_infer_fk_relations_ignores_missing_target_when_configured() -> None:
    frames = {
        "product": pd.DataFrame({"id_(missing_target)": ["x"]}),
    }
    out = infer_fk_relations(frames, on_missing_target="ignore")
    assert out["_meta"]["helper_policies"]["fk"]["relations"] == []
    assert out["_meta"]["helper_policies"]["fk"]["schema_version"] == SCHEMA_VERSION


def test_infer_fk_relations_raises_on_ambiguous_when_configured() -> None:
    # Two frames normalize to the same sheet key "PM" via whitespace-to-underscore
    # rule; the target token "PM" is genuinely ambiguous.
    frames = {
        "PM": pd.DataFrame({"id": ["m1"], "name": ["Alice"]}),
        " PM ": pd.DataFrame({"id": ["m1"], "name": ["Alice2"]}),
        "product": pd.DataFrame({"id_(PM)": ["m1"]}),
    }
    with pytest.raises(ValueError, match="ambiguous"):
        infer_fk_relations(frames)


def test_infer_fk_relations_ignores_ambiguous_when_configured() -> None:
    frames = {
        "PM": pd.DataFrame({"id": ["m1"], "name": ["Alice"]}),
        " PM ": pd.DataFrame({"id": ["m1"], "name": ["Alice2"]}),
        "product": pd.DataFrame({"id_(PM)": ["m1"]}),
    }
    out = infer_fk_relations(frames, on_ambiguous="ignore")
    assert out["_meta"]["helper_policies"]["fk"]["relations"] == []


def test_infer_fk_relations_target_with_no_id_column_raises() -> None:
    frames = {
        "product_manager": pd.DataFrame({"code": ["m1"], "name": ["Alice"]}),
        "product": pd.DataFrame({"id_(product_manager)": ["m1"]}),
    }
    with pytest.raises(ValueError, match="no id column"):
        infer_fk_relations(frames)


def test_infer_fk_relations_emits_no_relations_when_no_fk_columns_found() -> None:
    frames = {
        "product": pd.DataFrame({"id": ["p1"], "name": ["Widget"]}),
    }
    out = infer_fk_relations(frames)
    fk_root = out["_meta"]["helper_policies"]["fk"]
    assert fk_root["schema_version"] == SCHEMA_VERSION
    assert fk_root["relations"] == []


def test_infer_fk_relations_then_configure_fk_helpers_compose_when_disjoint() -> None:
    # infer picks up the conventionally-named FK on `product`; configure adds
    # an explicit relation on `supplier_rel` using a custom FK column header
    # that infer's default pattern does not match.
    frames = _frames()
    frames["supplier"] = pd.DataFrame({"id": ["sup1"], "name": ["SuppCo"]})
    frames["supplier_rel"] = pd.DataFrame(
        {"id": ["sr1"], "supplier_key": ["sup1"]}
    )

    after_infer = infer_fk_relations(frames)
    after_explicit = configure_fk_helpers(
        after_infer,
        target="supplier",
        key="id",
        allowed_helpers=["name"],
        default_helpers=["name"],
        fk_column="supplier_key",
    )

    relations = after_explicit["_meta"]["helper_policies"]["fk"]["relations"]
    keys = {(r["source_frame"], r["source_column"]): r["produced_by"]["step"] for r in relations}
    assert keys == {
        ("product", "id_(product_manager)"): "infer_fk_relations",
        ("supplier_rel", "supplier_key"): "configure_fk_helpers",
    }


def test_conflicting_producers_on_same_relation_key_fail_clearly() -> None:
    frames = {
        "product_manager": pd.DataFrame({"id": ["m1"], "name": ["Alice"]}),
        "product": pd.DataFrame({"id_(product_manager)": ["m1"]}),
    }
    after_infer = infer_fk_relations(frames)
    with pytest.raises(ValueError, match="produced by"):
        configure_fk_helpers(
            after_infer,
            target="product_manager",
            key="id",
            allowed_helpers=["name"],
            default_helpers=["name"],
        )


def test_apply_v2_relations_is_idempotent_for_identical_same_producer_relation() -> None:
    frames = _frames()
    after_first = infer_fk_relations(frames)
    after_second = infer_fk_relations(after_first)
    first_relations = after_first["_meta"]["helper_policies"]["fk"]["relations"]
    second_relations = after_second["_meta"]["helper_policies"]["fk"]["relations"]
    assert len(second_relations) == 1
    # The retained relation must be unchanged content-wise, not just same key count.
    assert second_relations == first_relations


def _make_baseline_relation(**overrides) -> dict:
    defaults = dict(
        source_frame="product",
        source_column="id_(product_manager)",
        target_frame="product_manager",
        target_key="id",
        helper_fields=["name"],
        helper_columns=[{"column": "_product_manager_name", "target_field": "name"}],
        helper_prefix="_",
        produced_by_step="infer_fk_relations",
        produced_by_mode="naming_convention",
    )
    defaults.update(overrides)
    return build_v2_relation(**defaults)


def test_apply_v2_relations_rejects_same_producer_changed_helper_prefix() -> None:
    base = _make_baseline_relation()
    divergent = _make_baseline_relation(
        helper_prefix="__",
        helper_columns=[{"column": "__product_manager_name", "target_field": "name"}],
    )
    state = apply_v2_relations({}, [base])
    with pytest.raises(ValueError, match="different relation body"):
        apply_v2_relations(state, [divergent])


def test_apply_v2_relations_rejects_same_producer_changed_helper_fields() -> None:
    base = _make_baseline_relation()
    divergent = _make_baseline_relation(
        helper_fields=["name", "label"],
        helper_columns=[
            {"column": "_product_manager_name", "target_field": "name"},
            {"column": "_product_manager_label", "target_field": "label"},
        ],
    )
    state = apply_v2_relations({}, [base])
    with pytest.raises(ValueError, match="different relation body"):
        apply_v2_relations(state, [divergent])


def test_apply_v2_relations_rejects_same_producer_changed_target_key() -> None:
    base = _make_baseline_relation()
    divergent = _make_baseline_relation(target_key="code")
    state = apply_v2_relations({}, [base])
    with pytest.raises(ValueError, match="different relation body"):
        apply_v2_relations(state, [divergent])


def test_apply_v2_relations_rejects_same_producer_changed_target_frame() -> None:
    base = _make_baseline_relation()
    divergent = _make_baseline_relation(target_frame="ProductManagers")
    state = apply_v2_relations({}, [base])
    with pytest.raises(ValueError, match="different relation body"):
        apply_v2_relations(state, [divergent])


def test_apply_v2_relations_rejects_same_producer_changed_mode() -> None:
    base = _make_baseline_relation()
    divergent = _make_baseline_relation(produced_by_mode="future_mode")
    state = apply_v2_relations({}, [base])
    with pytest.raises(ValueError, match="different relation body"):
        apply_v2_relations(state, [divergent])


def test_apply_v2_relations_cross_producer_conflict_still_fails() -> None:
    base = _make_baseline_relation()
    cross = _make_baseline_relation(produced_by_step="configure_fk_helpers", produced_by_mode="explicit")
    state = apply_v2_relations({}, [base])
    with pytest.raises(ValueError, match="produced by"):
        apply_v2_relations(state, [cross])


def test_apply_v2_relations_writes_schema_version_even_for_empty_relations() -> None:
    out = apply_v2_relations({}, [])
    fk_root = out["_meta"]["helper_policies"]["fk"]
    assert fk_root["schema_version"] == SCHEMA_VERSION
    assert fk_root["relations"] == []


def test_infer_fk_relations_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unknown mode"):
        infer_fk_relations(_frames(), mode="future_mode")


def test_infer_fk_relations_rejects_invalid_pattern() -> None:
    with pytest.raises(ValueError, match="placeholder"):
        infer_fk_relations(_frames(), fk_patterns=["id_no_placeholder"])
