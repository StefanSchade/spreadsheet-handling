"""Contract tests for the pure XRef axis-mapping model and resolver."""
from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.xref_axis_mapping import (
    AxisMappingError,
    AxisMappingIntent,
    AxisOrderPolicy,
    ResolvedAxisMapping,
    resolve_axis_mapping,
)

pytestmark = pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")


def _intent(
    *,
    labels: tuple[str, ...] = ("label",),
    order_policy: AxisOrderPolicy = AxisOrderPolicy.SOURCE_ROW,
    order_columns: tuple[str, ...] = (),
) -> AxisMappingIntent:
    return AxisMappingIntent(
        source_frame="axis",
        key_column="key",
        label_columns=labels,
        order_policy=order_policy,
        order_columns=order_columns,
    )


class _NotTotallyOrdered(str):
    def __new__(cls, value: str) -> _NotTotallyOrdered:
        return super().__new__(cls, value)

    def __lt__(self, other: object) -> bool:
        return False


class _ExplosiveEquality:
    def __eq__(self, other: object) -> bool:
        raise RuntimeError("do not leak")

    def __repr__(self) -> str:
        return "_ExplosiveEquality()"


class TestValidResolution:
    def test_one_level_mapping_supports_exact_forward_and_inverse_lookup(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["CHAR-0002"],
                "label": ["Galli"],
            })
        }

        resolved = resolve_axis_mapping(frames, _intent(), used_keys=["CHAR-0002"])

        assert isinstance(resolved, ResolvedAxisMapping)
        assert resolved.label_arity == 1
        assert [(member.key, member.labels, member.position) for member in resolved] == [
            ("CHAR-0002", ("Galli",), 0)
        ]
        assert resolved.labels_for_key("CHAR-0002") == ("Galli",)
        assert resolved.key_for_labels(("Galli",)) == "CHAR-0002"

    def test_two_level_mapping_allows_repeated_upper_levels(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": [
                    "credit.fixed_rate_loan",
                    "deposit.balance",
                    "credit.annuity_loan",
                ],
                "family": ["Kredit", "Einlage", "Kredit"],
                "product": [
                    "Festzinsdarlehen",
                    "Guthaben",
                    "Annuitätendarlehen",
                ],
                "family_order": [1, 2, 1],
                "product_order": [2, 1, 1],
            })
        }
        intent = _intent(
            labels=("family", "product"),
            order_policy=AxisOrderPolicy.COLUMNS,
            order_columns=("family_order", "product_order"),
        )

        resolved = resolve_axis_mapping(frames, intent)

        assert [(member.key, member.labels, member.position) for member in resolved] == [
            (
                "credit.annuity_loan",
                ("Kredit", "Annuitätendarlehen"),
                0,
            ),
            (
                "credit.fixed_rate_loan",
                ("Kredit", "Festzinsdarlehen"),
                1,
            ),
            ("deposit.balance", ("Einlage", "Guthaben"), 2),
        ]
        assert (
            resolved.key_for_labels(("Kredit", "Festzinsdarlehen"))
            == "credit.fixed_rate_loan"
        )

    def test_three_level_mapping_uses_the_same_model(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["credit.annuity_loan", "deposit.balance"],
                "segment": ["Retail", "Retail"],
                "family": ["Kredit", "Einlage"],
                "product": ["Annuitätendarlehen", "Guthaben"],
            })
        }

        resolved = resolve_axis_mapping(
            frames,
            _intent(labels=("segment", "family", "product")),
        )

        assert resolved.label_arity == 3
        assert resolved.labels_for_key("credit.annuity_loan") == (
            "Retail",
            "Kredit",
            "Annuitätendarlehen",
        )
        assert (
            resolved.key_for_labels(("Retail", "Einlage", "Guthaben"))
            == "deposit.balance"
        )

    def test_source_row_order_is_used_only_when_explicitly_selected(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-b", "key-a"],
                "label": ["Second", "First"],
            })
        }

        resolved = resolve_axis_mapping(
            frames,
            _intent(order_policy=AxisOrderPolicy.SOURCE_ROW),
        )

        assert [member.key for member in resolved] == ["key-b", "key-a"]
        assert [member.position for member in resolved] == [0, 1]

    def test_configured_order_ties_use_canonical_key_as_final_tie_breaker(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-b", "key-a", "key-c"],
                "label": ["B", "A", "C"],
                "rank": [1, 1, 2],
            })
        }

        resolved = resolve_axis_mapping(
            frames,
            _intent(
                order_policy=AxisOrderPolicy.COLUMNS,
                order_columns=("rank",),
            ),
        )

        assert [member.key for member in resolved] == ["key-a", "key-b", "key-c"]

    def test_empty_source_resolves_to_an_arity_preserving_empty_bijection(self) -> None:
        frames = {
            "axis": pd.DataFrame(columns=["key", "family", "product", "rank"])
        }
        intent = _intent(
            labels=("family", "product"),
            order_policy=AxisOrderPolicy.COLUMNS,
            order_columns=("rank",),
        )

        resolved = resolve_axis_mapping(frames, intent)

        assert resolved.members == ()
        assert resolved.label_columns == ("family", "product")
        assert resolved.label_arity == 2

    def test_matching_preserves_case_whitespace_and_delimiter_text_exactly(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key"],
                "label": [" Kredit / Retail "],
            })
        }

        resolved = resolve_axis_mapping(frames, _intent())

        assert resolved.labels_for_key("key") == (" Kredit / Retail ",)
        assert resolved.key_for_labels((" Kredit / Retail ",)) == "key"
        with pytest.raises(AxisMappingError, match="Unknown complete"):
            resolved.key_for_labels(("kredit / retail",))

    def test_repeated_used_keys_are_a_completeness_check_not_a_uniqueness_rule(
        self,
    ) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a"],
                "label": ["A"],
            })
        }

        resolved = resolve_axis_mapping(
            frames,
            _intent(),
            used_keys=["key-a", "key-a"],
        )

        assert len(resolved) == 1

    def test_resolution_and_members_are_frozen(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a"],
                "label": ["A"],
            })
        }
        resolved = resolve_axis_mapping(frames, _intent())

        with pytest.raises(FrozenInstanceError):
            resolved.members = ()  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            resolved.members[0].position = 2  # type: ignore[misc]


class TestInvalidDeclarationAndSchema:
    @pytest.mark.parametrize(
        ("field", "value", "match"),
        [
            ("source_frame", "", "source_frame"),
            ("key_column", " ", "key_column"),
            ("label_columns", (), "at least one"),
            ("label_columns", "label", "ordered sequence"),
            ("label_columns", {"label"}, "ordered sequence"),
            ("label_columns", {"label": 1}, "ordered sequence"),
            ("label_columns", ("label", "label"), "duplicate field"),
        ],
    )
    def test_malformed_declaration_is_rejected(
        self,
        field: str,
        value: object,
        match: str,
    ) -> None:
        values: dict[str, object] = {
            "source_frame": "axis",
            "key_column": "key",
            "label_columns": ("label",),
            "order_policy": AxisOrderPolicy.SOURCE_ROW,
            "order_columns": (),
        }
        values[field] = value

        with pytest.raises(AxisMappingError, match=match):
            AxisMappingIntent(**values)  # type: ignore[arg-type]

    def test_order_policy_must_be_deliberately_typed(self) -> None:
        with pytest.raises(AxisMappingError, match="AxisOrderPolicy"):
            AxisMappingIntent(
                source_frame="axis",
                key_column="key",
                label_columns=("label",),
                order_policy="source_row",  # type: ignore[arg-type]
            )

    def test_source_row_policy_rejects_order_columns(self) -> None:
        with pytest.raises(AxisMappingError, match="must be empty"):
            _intent(
                order_policy=AxisOrderPolicy.SOURCE_ROW,
                order_columns=("rank",),
            )

    def test_column_policy_requires_order_columns(self) -> None:
        with pytest.raises(AxisMappingError, match="at least one"):
            _intent(order_policy=AxisOrderPolicy.COLUMNS)

    def test_missing_source_frame_has_feature_diagnostic(self) -> None:
        with pytest.raises(AxisMappingError, match="source frame 'axis'.*not found"):
            resolve_axis_mapping({}, _intent())

    def test_source_must_be_a_dataframe(self) -> None:
        with pytest.raises(AxisMappingError, match="pandas DataFrame"):
            resolve_axis_mapping({"axis": [{"key": "a", "label": "A"}]}, _intent())

    @pytest.mark.parametrize(
        ("columns", "match"),
        [
            (["label"], r"missing configured column.*key"),
            (["key"], r"missing configured column.*label"),
            (["key", "label"], r"missing configured column.*rank"),
        ],
    )
    def test_missing_configured_columns_are_rejected(
        self,
        columns: list[str],
        match: str,
    ) -> None:
        frame = pd.DataFrame(columns=columns)
        intent = _intent(
            order_policy=AxisOrderPolicy.COLUMNS,
            order_columns=("rank",),
        )

        with pytest.raises(AxisMappingError, match=match):
            resolve_axis_mapping({"axis": frame}, intent)

    def test_duplicate_physical_columns_fail_before_selection(self) -> None:
        frame = pd.DataFrame(
            [["a", "A", "B"]],
            columns=pd.Index(["key", "label", "label"], dtype=object),
        )

        with pytest.raises(AxisMappingError, match="duplicate physical column"):
            resolve_axis_mapping({"axis": frame}, _intent())

    def test_unhashable_physical_column_fails_with_feature_diagnostic(self) -> None:
        labels = np.empty(3, dtype=object)
        labels[:] = ["key", "label", ["bad"]]
        frame = pd.DataFrame(
            [["a", "A", "unused"]],
            columns=pd.Index(labels, dtype=object),
        )

        with pytest.raises(AxisMappingError, match="unhashable physical column"):
            resolve_axis_mapping({"axis": frame}, _intent())


class TestInvalidSourceValues:
    @pytest.mark.parametrize("key", [None, np.nan, pd.NA, "", " ", 7, ["key"]])
    def test_canonical_keys_must_be_present_non_empty_strings(self, key: object) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": [key],
                "label": ["A"],
            })
        }

        with pytest.raises(AxisMappingError, match="canonical key.*non-empty string"):
            resolve_axis_mapping(frames, _intent())

    def test_duplicate_canonical_keys_are_rejected(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a", "key-a"],
                "label": ["A", "B"],
            })
        }

        with pytest.raises(AxisMappingError, match="duplicate canonical key 'key-a'"):
            resolve_axis_mapping(frames, _intent())

    def test_duplicate_complete_label_tuples_are_rejected(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a", "key-b"],
                "family": ["Kredit", "Kredit"],
                "product": ["Produkt", "Produkt"],
            })
        }

        with pytest.raises(AxisMappingError, match="duplicate complete visible label tuple"):
            resolve_axis_mapping(
                frames,
                _intent(labels=("family", "product")),
            )

    @pytest.mark.parametrize(
        ("label", "match"),
        [
            (None, "missing"),
            (np.nan, "missing"),
            (pd.NA, "missing"),
            ("", "empty"),
            (" ", "empty"),
            (7, "non-string"),
            (["A"], "non-scalar/unhashable"),
            (np.array([1, 2]), "ambiguous equality"),
            (_ExplosiveEquality(), "ambiguous equality"),
        ],
    )
    def test_visible_labels_fail_through_deliberate_diagnostics(
        self,
        label: object,
        match: str,
    ) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a"],
                "label": [label],
            })
        }

        with pytest.raises(AxisMappingError, match=match):
            resolve_axis_mapping(frames, _intent())

    def test_invalid_label_precedes_duplicate_key_hashing_or_bijection_checks(
        self,
    ) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a", "key-a"],
                "label": [["bad"], "B"],
            })
        }

        with pytest.raises(AxisMappingError, match="visible label.*unhashable"):
            resolve_axis_mapping(frames, _intent())

    def test_unknown_used_key_is_rejected_after_complete_mapping_validation(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a"],
                "label": ["A"],
            })
        }

        with pytest.raises(AxisMappingError, match=r"Used canonical.*key-b.*missing"):
            resolve_axis_mapping(frames, _intent(), used_keys=["key-b"])

    @pytest.mark.parametrize("used_key", [None, 1, [], np.array([1, 2]), " "])
    def test_malformed_used_keys_get_feature_diagnostics(self, used_key: object) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a"],
                "label": ["A"],
            })
        }

        with pytest.raises(AxisMappingError, match=r"used_keys\[0\]"):
            resolve_axis_mapping(frames, _intent(), used_keys=[used_key])


class TestInvalidOrdering:
    @pytest.mark.parametrize("order_value", [None, np.nan, pd.NA])
    def test_missing_order_values_are_rejected(self, order_value: object) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a"],
                "label": ["A"],
                "rank": [order_value],
            })
        }

        with pytest.raises(AxisMappingError, match="order column 'rank'.*missing"):
            resolve_axis_mapping(
                frames,
                _intent(
                    order_policy=AxisOrderPolicy.COLUMNS,
                    order_columns=("rank",),
                ),
            )

    def test_non_scalar_order_value_is_rejected(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a"],
                "label": ["A"],
                "rank": [[1, 2]],
            })
        }

        with pytest.raises(AxisMappingError, match="order column 'rank'.*non-scalar"):
            resolve_axis_mapping(
                frames,
                _intent(
                    order_policy=AxisOrderPolicy.COLUMNS,
                    order_columns=("rank",),
                ),
            )

    def test_mixed_non_comparable_order_values_are_rejected(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a", "key-b"],
                "label": ["A", "B"],
                "rank": [1, "1"],
            })
        }

        with pytest.raises(AxisMappingError, match="cannot be compared deterministically"):
            resolve_axis_mapping(
                frames,
                _intent(
                    order_policy=AxisOrderPolicy.COLUMNS,
                    order_columns=("rank",),
                ),
            )

    def test_non_total_order_is_rejected_as_non_deterministic(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a", "key-b"],
                "label": ["A", "B"],
                "rank": [_NotTotallyOrdered("a"), _NotTotallyOrdered("b")],
            })
        }

        with pytest.raises(AxisMappingError, match="do not define deterministic"):
            resolve_axis_mapping(
                frames,
                _intent(
                    order_policy=AxisOrderPolicy.COLUMNS,
                    order_columns=("rank",),
                ),
            )


class TestLookupValidation:
    @pytest.fixture
    def resolved(self) -> ResolvedAxisMapping:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a"],
                "family": ["Kredit"],
                "product": ["Produkt"],
            })
        }
        return resolve_axis_mapping(
            frames,
            _intent(labels=("family", "product")),
        )

    def test_wrong_tuple_arity_is_rejected(self, resolved: ResolvedAxisMapping) -> None:
        with pytest.raises(AxisMappingError, match="tuple arity 1; expected 2"):
            resolved.key_for_labels(("Kredit",))

    def test_joined_string_is_not_an_inverse_identity(
        self,
        resolved: ResolvedAxisMapping,
    ) -> None:
        with pytest.raises(AxisMappingError, match="must be a tuple"):
            resolved.key_for_labels("Kredit / Produkt")  # type: ignore[arg-type]

    def test_unknown_key_is_rejected(self, resolved: ResolvedAxisMapping) -> None:
        with pytest.raises(AxisMappingError, match="Unknown canonical axis key"):
            resolved.labels_for_key("KEY-A")

    def test_unknown_full_tuple_is_rejected(self, resolved: ResolvedAxisMapping) -> None:
        with pytest.raises(AxisMappingError, match="Unknown complete"):
            resolved.key_for_labels(("Kredit", "Anderes Produkt"))

    def test_non_scalar_lookup_label_is_rejected_deliberately(
        self,
        resolved: ResolvedAxisMapping,
    ) -> None:
        with pytest.raises(AxisMappingError, match="non-empty string"):
            resolved.key_for_labels(("Kredit", ["Produkt"]))  # type: ignore[arg-type]


class TestPurityAndAtomicity:
    def test_success_leaves_the_complete_caller_graph_unchanged(self) -> None:
        source = pd.DataFrame({
            "key": ["key-a", "key-b"],
            "label": ["A", "B"],
        })
        other = pd.DataFrame({"value": [1]})
        nested = {"sentinel": ["keep", {"deep": True}]}
        frames = {
            "axis": source,
            "other": other,
            "_meta": nested,
        }
        snapshot = copy.deepcopy(frames)
        source_id = id(source)
        other_id = id(other)
        meta_id = id(nested)
        sentinel_id = id(nested["sentinel"])
        deep_id = id(nested["sentinel"][1])

        resolve_axis_mapping(frames, _intent())

        assert id(frames["axis"]) == source_id
        assert id(frames["other"]) == other_id
        assert id(frames["_meta"]) == meta_id
        assert id(frames["_meta"]["sentinel"]) == sentinel_id
        assert id(frames["_meta"]["sentinel"][1]) == deep_id
        pd.testing.assert_frame_equal(frames["axis"], snapshot["axis"])
        pd.testing.assert_frame_equal(frames["other"], snapshot["other"])
        assert frames["_meta"] == snapshot["_meta"]

    def test_failed_resolution_leaves_the_complete_caller_graph_unchanged(
        self,
    ) -> None:
        source = pd.DataFrame({
            "key": ["key-a", "key-b"],
            "label": ["A", "A"],
        })
        other = pd.DataFrame({"value": [1]})
        nested = {"sentinel": ["keep", {"deep": True}]}
        frames = {
            "axis": source,
            "other": other,
            "_meta": nested,
        }
        snapshot = copy.deepcopy(frames)
        graph_ids = {
            "source": id(source),
            "other": id(other),
            "meta": id(nested),
            "sentinel": id(nested["sentinel"]),
            "deep": id(nested["sentinel"][1]),
        }

        with pytest.raises(AxisMappingError, match="duplicate complete"):
            resolve_axis_mapping(frames, _intent())

        assert id(frames["axis"]) == graph_ids["source"]
        assert id(frames["other"]) == graph_ids["other"]
        assert id(frames["_meta"]) == graph_ids["meta"]
        assert id(frames["_meta"]["sentinel"]) == graph_ids["sentinel"]
        assert id(frames["_meta"]["sentinel"][1]) == graph_ids["deep"]
        pd.testing.assert_frame_equal(frames["axis"], snapshot["axis"])
        pd.testing.assert_frame_equal(frames["other"], snapshot["other"])
        assert frames["_meta"] == snapshot["_meta"]
