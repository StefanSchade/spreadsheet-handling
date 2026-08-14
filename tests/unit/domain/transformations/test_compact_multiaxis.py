from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
import pytest

from spreadsheet_handling.domain.pipeline_cleanup import execute_final_domain_cleanup
from spreadsheet_handling.domain.transformations.compact_multiaxis import (
    contract_compact_multiaxis,
    expand_compact_multiaxis,
)
from spreadsheet_handling.domain.transformations.xref_crosstable import (
    contract_xref,
    expand_xref,
)


pytestmark = [
    pytest.mark.ftr("FTR-COMPACT-MULTIAXIS"),
    pytest.mark.ftr("FTR-COMPACT-MULTIAXIS-META-PERSISTENCE-CORRECTION-P5"),
]
SELECTOR_FTR = pytest.mark.ftr("FTR-XREF-PHYSICAL-LABEL-METADATA-AUTHORITY-P4A")


class _ProtocolBomb:
    """A hostile object whose protocol methods must never execute.

    Records into a caller-supplied list and raises immediately, so a test
    can assert both "the candidate's own methods never ran" (``calls ==
    []``) and, if one somehow did run, fail loudly rather than silently.
    """

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def __repr__(self) -> str:  # pragma: no cover - must never run
        self._calls.append("repr")
        raise AssertionError("repr must not run")

    def __str__(self) -> str:  # pragma: no cover - must never run
        self._calls.append("str")
        raise AssertionError("str must not run")

    def __eq__(self, other: object) -> bool:  # pragma: no cover - must never run
        self._calls.append("eq")
        raise AssertionError("equality must not run")

    def __hash__(self) -> int:  # pragma: no cover - must never run
        self._calls.append("hash")
        raise AssertionError("hashing must not run")

    def __iter__(self):  # pragma: no cover - must never run
        self._calls.append("iter")
        raise AssertionError("iteration must not run")


def _legend_meta() -> dict:
    return {
        "legend_blocks": {
            "status_codes": {
                "entries": [
                    {"token": "E", "label": "Editable", "group": "input"},
                    {"token": "E-R-K", "label": "Composite whole code", "group": "input"},
                    {"token": "S", "label": "System", "group": "system"},
                ],
            }
        }
    }


def _assert_no_internal_temp_reference(value: Any) -> None:
    if isinstance(value, str):
        assert "__compact_multiaxis_" not in value
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_no_internal_temp_reference(key)
            _assert_no_internal_temp_reference(child)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            _assert_no_internal_temp_reference(child)


def test_expand_compact_multiaxis_produces_generic_long_form_with_legend_group() -> None:
    frames = {
        "product_matrix": pd.DataFrame(
            {
                "feature_id": ["f1", "f2"],
                "P-001": ["E", "S"],
                "P-002": ["E-R-K", ""],
            }
        ),
        "_meta": _legend_meta(),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="product_matrix",
        output="feature_product_codes",
        row_keys=["feature_id"],
        value_columns=["P-001", "P-002"],
        allowed_from_legend="status_codes",
        group="group",
    )

    assert out["feature_product_codes"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E", "group": "input"},
        {"feature_id": "f1", "column_key": "P-002", "code": "E-R-K", "group": "input"},
        {"feature_id": "f2", "column_key": "P-001", "code": "S", "group": "system"},
    ]
    assert "__compact_multiaxis_feature_product_codes_xref" not in out
    assert out["_meta"]["compact_multiaxis"]["feature_product_codes"]["drop_empty"] is True
    assert "frame_lifecycle" not in out["_meta"]


def test_expand_compact_multiaxis_can_project_explicit_code_groups_without_legend() -> None:
    frames = {
        "product_matrix": pd.DataFrame(
            {
                "feature_id": ["f1", "f2"],
                "P-001": ["E", "S"],
            }
        )
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="product_matrix",
        output="feature_product_codes",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        allowed_codes=["E", "S"],
        code_groups={"E": "input", "S": "system"},
        group="group",
    )

    assert out["feature_product_codes"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E", "group": "input"},
        {"feature_id": "f2", "column_key": "P-001", "code": "S", "group": "system"},
    ]
    assert out["_meta"]["compact_multiaxis"]["feature_product_codes"]["code_groups"] == {
        "E": "input",
        "S": "system",
    }


def test_conflicting_legend_and_explicit_code_groups_are_rejected() -> None:
    frames = {
        "product_matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "P-001": ["E"],
            }
        ),
        "_meta": _legend_meta(),
    }

    with pytest.raises(ValueError, match="Conflicting group value"):
        expand_compact_multiaxis(
            frames,
            matrix="product_matrix",
            output="feature_product_codes",
            row_keys=["feature_id"],
            value_columns=["P-001"],
            allowed_from_legend="status_codes",
            code_groups={"E": "other"},
            group="group",
        )


def test_compact_multiaxis_whole_cell_roundtrip_can_preserve_empty_cells_when_configured() -> None:
    frames = {
        "product_matrix": pd.DataFrame(
            {
                "feature_id": ["f1", "f2"],
                "P-001": ["E", "S"],
                "P-002": ["E-R-K", ""],
            }
        ),
        "_meta": _legend_meta(),
    }
    expanded = expand_compact_multiaxis(
        frames,
        matrix="product_matrix",
        output="feature_product_codes",
        row_keys=["feature_id"],
        value_columns=["P-001", "P-002"],
        allowed_from_legend="status_codes",
        drop_empty=False,
    )

    out = contract_compact_multiaxis(
        expanded,
        relation="feature_product_codes",
        output="product_matrix_roundtrip",
        row_keys=["feature_id"],
        allowed_from_legend="status_codes",
    )

    assert out["product_matrix_roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E", "P-002": "E-R-K"},
        {"feature_id": "f2", "P-001": "S", "P-002": ""},
    ]
    assert "frame_lifecycle" not in out["_meta"]


def test_compact_multiaxis_sparse_default_keeps_sparse_relations_sparse() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1", "f2"],
                "P-001": ["E", ""],
            }
        ),
        "_meta": _legend_meta(),
    }

    expanded = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        allowed_from_legend="status_codes",
    )
    out = contract_compact_multiaxis(
        expanded,
        relation="explicit",
        output="roundtrip",
        row_keys=["feature_id"],
        allowed_from_legend="status_codes",
    )

    assert out["explicit"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "E"},
    ]
    assert out["roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E"},
    ]


@pytest.mark.ftr("FTR-COMPACT-TRANSFORM-API-ERGONOMICS-P4")
def test_display_labels_roundtrip_only_when_configured_as_row_keys() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "feature_label": ["Display label"],
                "P-001": ["E"],
            }
        ),
        "_meta": _legend_meta(),
    }

    without_label = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        allowed_from_legend="status_codes",
    )
    without_label_roundtrip = contract_compact_multiaxis(
        without_label,
        relation="explicit",
        output="roundtrip_without_label",
        row_keys=["feature_id"],
        allowed_from_legend="status_codes",
    )

    with_label = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit_with_label",
        row_keys=["feature_id", "feature_label"],
        value_columns=["P-001"],
        allowed_from_legend="status_codes",
    )
    with_label_roundtrip = contract_compact_multiaxis(
        with_label,
        relation="explicit_with_label",
        output="roundtrip_with_label",
        row_keys=["feature_id", "feature_label"],
        allowed_from_legend="status_codes",
    )

    assert without_label_roundtrip["roundtrip_without_label"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E"},
    ]
    assert with_label_roundtrip["roundtrip_with_label"].to_dict(orient="records") == [
        {"feature_id": "f1", "feature_label": "Display label", "P-001": "E"},
    ]


def test_split_token_multiaxis_roundtrip_uses_canonical_order() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "P-001": ["K-E"],
            }
        )
    }

    expanded = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit",
        row_keys=["feature_id"],
        value_columns=["P-001"],
        mode="split_tokens",
        delimiter="-",
        allowed_tokens=["E", "K"],
    )
    out = contract_compact_multiaxis(
        expanded,
        relation="explicit",
        output="roundtrip",
        row_keys=["feature_id"],
        mode="split_tokens",
        delimiter="-",
        allowed_tokens=["E", "K"],
        canonical_order=["E", "K"],
    )

    assert expanded["explicit"].to_dict(orient="records") == [
        {"feature_id": "f1", "column_key": "P-001", "code": "K"},
        {"feature_id": "f1", "column_key": "P-001", "code": "E"},
    ]
    assert out["roundtrip"].to_dict(orient="records") == [
        {"feature_id": "f1", "P-001": "E-K"},
    ]


def test_expand_rejects_dense_axes_until_explicitly_implemented() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "P-001": ["E"],
            }
        )
    }

    with pytest.raises(NotImplementedError, match="dense_axes"):
        expand_compact_multiaxis(
            frames,
            matrix="matrix",
            output="explicit",
            row_keys=["feature_id"],
            dense_axes={
                "rows_from": {"frame": "Products", "key": "product_id"},
            },
        )


@pytest.mark.ftr("FTR-COMPACT-TRANSFORM-API-ERGONOMICS-P4")
def test_missing_legend_block_error_points_to_allowed_from_legend() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "P-001": ["E"],
            }
        )
    }

    with pytest.raises(KeyError, match="allowed_from_legend.*status_codes"):
        expand_compact_multiaxis(
            frames,
            matrix="matrix",
            output="explicit",
            row_keys=["feature_id"],
            value_columns=["P-001"],
            allowed_from_legend="status_codes",
            group="group",
        )


def test_contract_rejects_dense_axes_until_explicitly_implemented() -> None:
    frames = {
        "explicit": pd.DataFrame(
            [
                {"feature_id": "f1", "column_key": "P-001", "code": "E"},
            ]
        )
    }

    with pytest.raises(NotImplementedError, match="dense_axes"):
        contract_compact_multiaxis(
            frames,
            relation="explicit",
            output="matrix",
            row_keys=["feature_id"],
            dense_axes={
                "rows_from": {"frame": "Products", "key": "product_id"},
                "columns_from": {"frame": "Markets", "key": "market_id"},
            },
        )


def test_expand_suppresses_internal_xref_meta_when_no_prior_root_exists() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "P-001": ["E"],
            }
        ),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit",
        row_keys=["feature_id"],
    )

    assert "xref_crosstable" not in out["_meta"]
    _assert_no_internal_temp_reference(out["_meta"])


def test_contract_suppresses_internal_xref_meta_when_no_prior_root_exists() -> None:
    frames = {
        "explicit": pd.DataFrame(
            [
                {"feature_id": "f1", "column_key": "P-001", "code": "E"},
            ]
        ),
    }

    out = contract_compact_multiaxis(
        frames,
        relation="explicit",
        output="matrix",
        row_keys=["feature_id"],
    )

    assert "xref_crosstable" not in out["_meta"]
    _assert_no_internal_temp_reference(out["_meta"])


def test_empty_prior_xref_root_is_omitted_after_internal_leg() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "P-001": ["E"],
            }
        ),
        "_meta": {"xref_crosstable": {}},
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit",
        row_keys=["feature_id"],
    )

    assert "xref_crosstable" not in out["_meta"]
    assert frames["_meta"] == {"xref_crosstable": {}}


def test_unrelated_xref_entries_survive_without_internal_config_entry() -> None:
    unrelated = {
        "relation": "other_relation",
        "matrix": "other_matrix",
        "row_keys": ["id"],
        "column_keys": ["B", "A"],
    }
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "P-001": ["E"],
            }
        ),
        "_meta": {"xref_crosstable": {"other": unrelated}},
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit",
        row_keys=["feature_id"],
        name="compact",
    )

    assert out["_meta"]["xref_crosstable"] == {"other": unrelated}
    assert "compact" not in out["_meta"]["xref_crosstable"]


def test_prior_same_id_xref_entry_is_restored_exactly_and_defensively() -> None:
    prior_entry = {
        "relation": "public_relation",
        "matrix": "public_matrix",
        "row_keys": ["feature_id"],
        "column_keys": ["P-002", "P-001"],
        "dense_axes": {
            "columns_from": {"frame": "products", "key": "name"},
            "resolved": {"column_keys": ["P-002", "P-001"]},
        },
    }
    frames = {
        "explicit": pd.DataFrame(
            [
                {"feature_id": "f1", "column_key": "P-001", "code": "E"},
                {"feature_id": "f1", "column_key": "P-002", "code": "S"},
            ]
        ),
        "_meta": {
            "xref_crosstable": {
                "compact": prior_entry,
                "other": {"relation": "other", "matrix": "other_matrix"},
            },
        },
    }
    before = copy.deepcopy(frames["_meta"])

    out = contract_compact_multiaxis(
        frames,
        relation="explicit",
        output="matrix",
        row_keys=["feature_id"],
        name="compact",
    )

    assert out["_meta"]["xref_crosstable"] == before["xref_crosstable"]
    assert frames["_meta"] == before
    restored = out["_meta"]["xref_crosstable"]["compact"]
    assert restored is not prior_entry
    assert restored["column_keys"] is not prior_entry["column_keys"]
    assert restored["dense_axes"] is not prior_entry["dense_axes"]
    assert list(out["matrix"].columns) == ["feature_id", "P-002", "P-001"]


def test_bare_xref_metadata_behavior_is_unchanged() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "P-001": ["E"],
            }
        ),
    }

    out = expand_xref(
        frames,
        matrix="matrix",
        output="relation",
        row_keys=["feature_id"],
        name="bare",
    )

    assert out["_meta"]["xref_crosstable"]["bare"] == {
        "matrix": "matrix",
        "relation": "relation",
        "row_keys": ["feature_id"],
        "column_keys": ["P-001"],
    }


def test_worldbuilding_shaped_bare_xref_intent_survives_compact_expand() -> None:
    frames = {
        "story_group_named": pd.DataFrame(
            [
                {"story_id": "s1", "group_name": "B", "code": "E"},
                {"story_id": "s1", "group_name": "A", "code": "K"},
            ]
        ),
    }
    contracted = contract_xref(
        frames,
        relation="story_group_named",
        output="story_group_matrix",
        row_keys=["story_id"],
        column_key="group_name",
        value="code",
        column_keys=["A", "B"],
        name="story_group_matrix",
    )
    prior_xref = copy.deepcopy(contracted["_meta"]["xref_crosstable"])

    out = expand_compact_multiaxis(
        contracted,
        matrix="story_group_matrix",
        output="story_group_named_reimported",
        row_keys=["story_id"],
        column_key="group_name",
        value="value",
        code="code",
        mode="whole_cell_code",
        drop_empty=True,
        name="story_group_matrix",
    )

    assert out["_meta"]["xref_crosstable"] == prior_xref
    assert out["story_group_named_reimported"].to_dict(orient="records") == [
        {"story_id": "s1", "group_name": "A", "code": "K"},
        {"story_id": "s1", "group_name": "B", "code": "E"},
    ]


def test_contract_explicit_column_keys_override_relation_order() -> None:
    frames = {
        "explicit": pd.DataFrame(
            [
                {"feature_id": "f1", "column_key": "A", "code": "E"},
                {"feature_id": "f1", "column_key": "B", "code": "K"},
            ]
        ),
    }

    out = contract_compact_multiaxis(
        frames,
        relation="explicit",
        output="matrix",
        row_keys=["feature_id"],
        column_keys=["B", "A"],
    )

    assert list(out["matrix"].columns) == ["feature_id", "B", "A"]
    assert out["_meta"]["compact_multiaxis"]["explicit"]["column_keys"] == ["B", "A"]


def test_contract_without_prior_xref_derives_first_occurrence_column_order() -> None:
    frames = {
        "explicit": pd.DataFrame(
            [
                {"feature_id": "f1", "column_key": "B", "code": "K"},
                {"feature_id": "f1", "column_key": "A", "code": "E"},
                {"feature_id": "f2", "column_key": "A", "code": "S"},
            ]
        ),
    }

    out = contract_compact_multiaxis(
        frames,
        relation="explicit",
        output="matrix",
        row_keys=["feature_id"],
    )

    assert list(out["matrix"].columns) == ["feature_id", "B", "A"]
    trace = out["_meta"]["compact_multiaxis"]["explicit"]
    assert trace["column_keys"] is None
    assert trace["canonical_order"] is None


def test_same_id_expand_then_contract_uses_relation_derived_order() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1", "f2"],
                "B": ["K", ""],
                "A": ["E", "S"],
            }
        ),
    }
    expanded = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit",
        row_keys=["feature_id"],
        drop_empty=True,
        name="shared",
    )

    out = contract_compact_multiaxis(
        expanded,
        relation="explicit",
        output="roundtrip",
        row_keys=["feature_id"],
        name="shared",
    )

    assert "xref_crosstable" not in expanded["_meta"]
    assert "xref_crosstable" not in out["_meta"]
    assert list(out["roundtrip"].columns) == ["feature_id", "B", "A"]


def test_sparse_roundtrip_column_order_is_deterministic_for_relation_row_order() -> None:
    first = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1", "f2"],
                "A": ["", "E"],
                "B": ["K", ""],
            }
        ),
    }
    reversed_rows = {
        "matrix": first["matrix"].iloc[::-1].reset_index(drop=True),
    }

    def roundtrip_columns(frames: dict[str, Any]) -> list[Any]:
        expanded = expand_compact_multiaxis(
            frames,
            matrix="matrix",
            output="explicit",
            row_keys=["feature_id"],
            drop_empty=True,
            name="shared",
        )
        contracted = contract_compact_multiaxis(
            expanded,
            relation="explicit",
            output="roundtrip",
            row_keys=["feature_id"],
            name="shared",
        )
        repeated = expand_compact_multiaxis(
            contracted,
            matrix="roundtrip",
            output="explicit_again",
            row_keys=["feature_id"],
            drop_empty=True,
            name="shared",
        )
        repeated_contract = contract_compact_multiaxis(
            repeated,
            relation="explicit_again",
            output="roundtrip_again",
            row_keys=["feature_id"],
            name="shared",
        )
        assert list(repeated_contract["roundtrip_again"].columns) == list(
            contracted["roundtrip"].columns
        )
        return list(contracted["roundtrip"].columns)

    assert roundtrip_columns(first) == ["feature_id", "B", "A"]
    assert roundtrip_columns(reversed_rows) == ["feature_id", "A", "B"]


def test_same_id_trace_replaces_atomically_without_history_accumulation() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "A": ["E"],
            }
        ),
    }
    expanded = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit",
        row_keys=["feature_id"],
        name="shared",
    )
    out = contract_compact_multiaxis(
        expanded,
        relation="explicit",
        output="roundtrip",
        row_keys=["feature_id"],
        name="shared",
    )

    configs = out["_meta"]["compact_multiaxis"]
    assert list(configs) == ["shared"]
    assert isinstance(configs["shared"], dict)
    assert configs["shared"]["operation"] == "contract_compact_multiaxis"
    assert not isinstance(configs["shared"], list)


def test_different_trace_ids_coexist_and_absence_does_not_prune() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "A": ["E"],
            }
        ),
    }
    first = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit_one",
        row_keys=["feature_id"],
        name="one",
    )
    out = expand_compact_multiaxis(
        first,
        matrix="matrix",
        output="explicit_two",
        row_keys=["feature_id"],
        name="two",
    )

    assert list(out["_meta"]["compact_multiaxis"]) == ["one", "two"]
    assert out["_meta"]["compact_multiaxis"]["one"] == first["_meta"]["compact_multiaxis"]["one"]


def test_failed_same_id_rerun_preserves_prior_trace_and_caller_state() -> None:
    initial = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "A": ["E"],
            }
        ),
        "_meta": {
            "xref_crosstable": {
                "shared": {
                    "relation": "caller_relation",
                    "matrix": "caller_matrix",
                    "row_keys": ["feature_id"],
                    "column_keys": ["A"],
                },
            },
        },
    }
    successful = expand_compact_multiaxis(
        initial,
        matrix="matrix",
        output="explicit",
        row_keys=["feature_id"],
        allowed_codes=["E"],
        name="shared",
    )
    prior_meta = copy.deepcopy(successful["_meta"])
    prior_matrix = successful["matrix"].copy(deep=True)

    with pytest.raises(ValueError, match="Invalid cell code"):
        expand_compact_multiaxis(
            successful,
            matrix="matrix",
            output="explicit_failed",
            row_keys=["feature_id"],
            allowed_codes=["K"],
            name="shared",
        )

    assert successful["_meta"] == prior_meta
    pd.testing.assert_frame_equal(successful["matrix"], prior_matrix)
    assert "explicit_failed" not in successful
    assert not any(key.startswith("__compact_multiaxis_") for key in successful)
    assert "pipeline_cleanup" not in successful["_meta"]


def test_trace_defensively_copies_authored_collections_and_mappings() -> None:
    allowed_codes = ["E"]
    code_groups = {" e ": {"label": ["input"]}}
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "A": [" e "],
            }
        ),
    }

    out = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit",
        row_keys=["feature_id"],
        value_columns=["A"],
        allowed_codes=allowed_codes,
        code_groups=code_groups,
        normalize_case="upper",
        strip=True,
    )
    trace = out["_meta"]["compact_multiaxis"]["explicit"]

    allowed_codes.append("K")
    code_groups[" e "]["label"].append("changed")

    assert trace["allowed_codes"] == ["E"]
    assert trace["code_groups"] == {"E": {"label": ["input"]}}
    assert trace["value_columns"] == ["A"]
    assert trace["normalize_case"] == "upper"
    assert trace["strip"] is True


def test_trace_records_authored_orders_without_backfilling_inference() -> None:
    frames = {
        "explicit": pd.DataFrame(
            [
                {"feature_id": "f1", "column_key": "B", "code": "K"},
                {"feature_id": "f1", "column_key": "A", "code": "E"},
            ]
        ),
    }
    authored_column_keys = ["A", "B"]
    authored_canonical_order = ["E", "K"]

    explicit = contract_compact_multiaxis(
        frames,
        relation="explicit",
        output="matrix_explicit",
        row_keys=["feature_id"],
        column_keys=authored_column_keys,
        mode="split_tokens",
        allowed_tokens=["E", "K"],
        canonical_order=authored_canonical_order,
        name="explicit_config",
    )
    inferred = contract_compact_multiaxis(
        frames,
        relation="explicit",
        output="matrix_inferred",
        row_keys=["feature_id"],
        name="inferred_config",
    )

    authored_column_keys.reverse()
    authored_canonical_order.reverse()
    explicit_trace = explicit["_meta"]["compact_multiaxis"]["explicit_config"]
    inferred_trace = inferred["_meta"]["compact_multiaxis"]["inferred_config"]
    assert explicit_trace["column_keys"] == ["A", "B"]
    assert explicit_trace["canonical_order"] == ["E", "K"]
    assert inferred_trace["column_keys"] is None
    assert inferred_trace["canonical_order"] is None


def test_conflicting_compact_trace_is_ignored_by_runtime() -> None:
    frames = {
        "explicit": pd.DataFrame(
            [
                {"feature_id": "f1", "column_key": "A", "code": "E"},
                {"feature_id": "f1", "column_key": "B", "code": "K"},
            ]
        ),
        "_meta": {
            "compact_multiaxis": {
                "shared": {
                    "mode": "WRONG",
                    "column_key": "BOGUS",
                    "code": "NOPE",
                    "column_keys": ["B", "A"],
                },
            },
        },
    }

    out = contract_compact_multiaxis(
        frames,
        relation="explicit",
        output="matrix",
        row_keys=["feature_id"],
        column_keys=["A", "B"],
        name="shared",
    )

    assert list(out["matrix"].columns) == ["feature_id", "A", "B"]
    assert out["matrix"].to_dict(orient="records") == [
        {"feature_id": "f1", "A": "E", "B": "K"},
    ]


def test_trace_and_final_cleanup_contain_only_public_frame_names() -> None:
    frames = {
        "matrix": pd.DataFrame(
            {
                "feature_id": ["f1"],
                "A": ["E"],
            }
        ),
    }
    expanded = expand_compact_multiaxis(
        frames,
        matrix="matrix",
        output="explicit",
        row_keys=["feature_id"],
    )
    with_cleanup = {
        **expanded,
        "_meta": {
            **expanded["_meta"],
            "pipeline_cleanup": {"keep_frames": ["matrix", "explicit"]},
        },
    }

    cleaned = execute_final_domain_cleanup(with_cleanup)

    assert "pipeline_cleanup" not in cleaned["_meta"]
    assert set(cleaned) == {"matrix", "explicit", "_meta"}
    _assert_no_internal_temp_reference(cleaned["_meta"])


@SELECTOR_FTR
class TestDurableSelectorReferenceInheritance:
    """Compact Multiaxis inherits the XRef durable selector-reference contract.

    FTR-XREF-PHYSICAL-LABEL-METADATA-AUTHORITY-P4A section 7.2: both
    composites build ``row_key_cols`` and forward it into the real
    ``expand_xref``/``contract_xref`` seam *before* writing their own
    ``_meta.compact_multiaxis.<id>.row_keys`` copy, so a non-conforming
    selector is rejected before that write and no independent, invalid
    Compact-Multiaxis trace is ever written. These tests verify that
    directly rather than inferring it from a code read.

    A rejection for a *single* invalid selector is raised by the inner
    ``contract_xref``/``expand_xref`` call, as originally documented. A
    composite ``row_keys`` list with a hostile, non-first candidate is
    instead rejected earlier, by this module's own preflight call to the
    same reused validator (XREF-SELECTOR-IMPL-REVIEW-F1 follow-up): both
    composites perform their own selector-sensitive work -- an output-name
    membership check (expand) or a Cell Codec ``group_by`` duplicate scan
    (contract) -- *before* ever reaching the inner XRef seam, and neither of
    those existing checks is safe to run against an unclassified candidate.
    The inner XRef seam remains the authoritative family gate for every
    other case.
    """

    def test_contract_compact_multiaxis_accepts_valid_str_row_key_selector(self) -> None:
        frames = {
            "explicit": pd.DataFrame([
                {"feature_id": "f1", "column_key": "A", "code": "E"},
            ]),
        }

        out = contract_compact_multiaxis(
            frames, relation="explicit", output="matrix", row_keys=["feature_id"]
        )

        assert out["_meta"]["compact_multiaxis"]["explicit"]["row_keys"] == ["feature_id"]

    def test_contract_compact_multiaxis_rejects_non_str_row_key_before_own_meta_write(
        self,
    ) -> None:
        # Physical column 7 exists on the source frame (Class A, unchanged)
        # so the rejection below is proven to come from the row_keys
        # selector-reference contract, not from a missing-column error.
        frames = {
            "explicit": pd.DataFrame([
                {7: "f1", "column_key": "A", "code": "E"},
            ]),
        }

        with pytest.raises(ValueError, match="selector reference"):
            contract_compact_multiaxis(
                frames, relation="explicit", output="matrix", row_keys=[7]
            )

        # No independent invalid trace: the inner XRef seam raised first, so
        # neither xref_crosstable nor compact_multiaxis metadata was written.
        assert "_meta" not in frames

    def test_expand_compact_multiaxis_rejects_non_str_row_key_before_own_meta_write(
        self,
    ) -> None:
        frames = {
            "product_matrix": pd.DataFrame({"feature_id": ["f1"], "P-001": ["E"]}),
        }

        with pytest.raises(ValueError, match="selector reference"):
            expand_compact_multiaxis(
                frames,
                matrix="product_matrix",
                output="feature_product_codes",
                row_keys=[7],
                value_columns=["P-001"],
            )

        assert "_meta" not in frames

    def test_contract_compact_multiaxis_rejects_composite_hostile_row_key_before_encode(
        self,
    ) -> None:
        # XREF-SELECTOR-IMPL-REVIEW-F1 follow-up: before the Compact preflight
        # existed, a non-first hostile row_keys candidate reached Cell Codec's
        # own group_by duplicate-field scan (via encode_cell_values), which
        # compares elements with candidate-controlled == before this contract
        # ever classifies them. The preflight must reject it first.
        calls: list[str] = []
        bomb = _ProtocolBomb(calls)
        frames = {
            "explicit": pd.DataFrame([
                {"feature_id": "f1", "column_key": "A", "code": "E"},
            ]),
        }

        with pytest.raises(ValueError, match="selector reference"):
            contract_compact_multiaxis(
                frames, relation="explicit", output="matrix", row_keys=["feature_id", bomb]
            )

        assert calls == []
        assert "_meta" not in frames

    def test_expand_compact_multiaxis_rejects_composite_hostile_row_key_before_collision_check(
        self,
    ) -> None:
        # XREF-SELECTOR-IMPL-REVIEW-F1 follow-up: before the Compact preflight
        # existed, a non-first hostile row_keys candidate reached this
        # composite's own _ensure_distinct_output_columns, which tests set
        # membership (hashing the candidate) before this contract ever
        # classifies it. The preflight must reject it first.
        calls: list[str] = []
        bomb = _ProtocolBomb(calls)
        frames = {
            "product_matrix": pd.DataFrame({"region": ["f1"], "P-001": ["E"]}),
        }

        with pytest.raises(ValueError, match="selector reference"):
            expand_compact_multiaxis(
                frames,
                matrix="product_matrix",
                output="out",
                row_keys=["region", bomb],
                value_columns=["P-001"],
            )

        assert calls == []
        assert "_meta" not in frames
