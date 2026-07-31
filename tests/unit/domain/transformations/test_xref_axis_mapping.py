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
    ResolvedAxisMember,
    resolve_axis_mapping,
)
import spreadsheet_handling.domain.transformations.xref_axis_mapping.resolver as resolver_module

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


class _CyclicOrder(str):
    comparisons = 0

    def __lt__(self, other: object) -> bool:
        type(self).comparisons += 1
        return (str(self), str(other)) in {("a", "b"), ("b", "c"), ("c", "a")}


class _AsymmetricOrder(str):
    comparisons = 0

    def __lt__(self, other: object) -> bool:
        type(self).comparisons += 1
        return str(self) != str(other)


class _NonTransitiveOrder(str):
    comparisons = 0

    def __lt__(self, other: object) -> bool:
        type(self).comparisons += 1
        return (str(self), str(other)) in {("a", "b"), ("b", "c")}


class _StatefulOrder(str):
    comparisons = 0

    def __lt__(self, other: object) -> bool:
        type(self).comparisons += 1
        return type(self).comparisons % 2 == 0


class _ExceptionRaisingOrder(str):
    comparisons = 0

    def __lt__(self, other: object) -> bool:
        type(self).comparisons += 1
        raise RuntimeError("comparison must not run")


class _EqualToEveryString:
    def __init__(self) -> None:
        self.string_comparisons = 0

    def __eq__(self, other: object) -> bool:
        if type(other) is str:
            self.string_comparisons += 1
            return True
        return other is self

    def __hash__(self) -> int:
        return 101

    def __repr__(self) -> str:
        return "_EqualToEveryString()"


class _HostileStripString(str):
    strip_calls = 0

    def strip(self, *args: object, **kwargs: object) -> str:
        type(self).strip_calls += 1
        raise RuntimeError("strip must not run")


class _HostileReprString(str):
    repr_calls = 0

    def __repr__(self) -> str:
        type(self).repr_calls += 1
        raise RuntimeError("repr must not run")


class _MutableHashString(str):
    hash_calls = 0

    def __new__(cls, value: str) -> _MutableHashString:
        instance = super().__new__(cls, value)
        instance.salt = 0
        return instance

    def __hash__(self) -> int:
        type(self).hash_calls += 1
        return super().__hash__() + self.salt


_hostile_type_name_calls = 0
_hostile_type_hash_calls = 0
_hostile_type_equality_calls = 0


class _HostileTypeMeta(type):
    def __getattribute__(cls, name: str) -> object:
        global _hostile_type_name_calls
        if name == "__name__":
            _hostile_type_name_calls += 1
            raise RuntimeError("type name must not be read")
        return super().__getattribute__(name)

    def __hash__(cls) -> int:
        global _hostile_type_hash_calls
        _hostile_type_hash_calls += 1
        raise RuntimeError("type hash must not run")

    def __eq__(cls, other: object) -> bool:
        global _hostile_type_equality_calls
        _hostile_type_equality_calls += 1
        raise RuntimeError("type equality must not run")


class _HostileType(metaclass=_HostileTypeMeta):
    pass


class _HostileMutableTuple(tuple[str, ...]):
    len_calls = 0
    iteration_calls = 0
    hash_calls = 0
    equality_calls = 0
    repr_calls = 0

    def __new__(cls, values: tuple[str, ...]) -> _HostileMutableTuple:
        instance = super().__new__(cls, values)
        instance.salt = 0
        return instance

    @classmethod
    def reset_calls(cls) -> None:
        cls.len_calls = 0
        cls.iteration_calls = 0
        cls.hash_calls = 0
        cls.equality_calls = 0
        cls.repr_calls = 0

    def __len__(self) -> int:
        type(self).len_calls += 1
        raise RuntimeError("length must not run")

    def __iter__(self) -> object:
        type(self).iteration_calls += 1
        raise RuntimeError("iteration must not run")

    def __hash__(self) -> int:
        type(self).hash_calls += 1
        return tuple.__hash__(self) + self.salt

    def __eq__(self, other: object) -> bool:
        type(self).equality_calls += 1
        raise RuntimeError("equality must not run")

    def __repr__(self) -> str:
        type(self).repr_calls += 1
        raise RuntimeError("representation must not run")


class _HostileNumpyInteger(np.int64):
    conversion_calls = 0

    def __int__(self) -> int:
        type(self).conversion_calls += 1
        raise RuntimeError("conversion must not run")


_NUMPY_INTEGER_ALIASES = (
    np.int8,
    np.int16,
    np.int32,
    np.int64,
    np.uint8,
    np.uint16,
    np.uint32,
    np.uint64,
    np.byte,
    np.ubyte,
    np.short,
    np.ushort,
    np.intc,
    np.uintc,
    np.int_,
    np.uint,
    np.longlong,
    np.ulonglong,
    np.intp,
    np.uintp,
)
_DISTINCT_NUMPY_INTEGER_TYPES = tuple(dict.fromkeys(_NUMPY_INTEGER_ALIASES))
_NULLABLE_INTEGER_DTYPES = (
    "Int8",
    "Int16",
    "Int32",
    "Int64",
    "UInt8",
    "UInt16",
    "UInt32",
    "UInt64",
)


def _forge_member_with_labels(labels: object) -> ResolvedAxisMember:
    member = object.__new__(ResolvedAxisMember)
    object.__setattr__(member, "key", "key-a")
    object.__setattr__(member, "labels", labels)
    object.__setattr__(member, "position", 0)
    return member


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
            (7, "unsupported value type"),
            (["A"], "unsupported value type"),
            (np.array([1, 2]), "unsupported value type"),
            (_ExplosiveEquality(), "unsupported value type"),
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

        with pytest.raises(AxisMappingError, match="visible label.*unsupported value type"):
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

        with pytest.raises(AxisMappingError, match="order column 'rank'.*exact built-in"):
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

        with pytest.raises(AxisMappingError, match="mixed types"):
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

        with pytest.raises(AxisMappingError, match="exact built-in"):
            resolve_axis_mapping(
                frames,
                _intent(
                    order_policy=AxisOrderPolicy.COLUMNS,
                    order_columns=("rank",),
                ),
            )


class TestAdversarialOrderValues:
    @staticmethod
    def _assert_rejected_before_comparison(
        values: list[str],
        value_type: type[str],
    ) -> None:
        value_type.comparisons = 0  # type: ignore[attr-defined]
        order_values = [value_type(value) for value in values]
        frames = {
            "axis": pd.DataFrame({
                "key": [f"key-{value}" for value in values],
                "label": [value.upper() for value in values],
                "rank": order_values,
            })
        }
        source = frames["axis"]
        source_id = id(source)
        meta = {"sentinel": ["unchanged"]}
        frames["_meta"] = meta

        with pytest.raises(AxisMappingError, match="exact built-in"):
            resolve_axis_mapping(
                frames,
                _intent(
                    order_policy=AxisOrderPolicy.COLUMNS,
                    order_columns=("rank",),
                ),
            )

        assert value_type.comparisons == 0  # type: ignore[attr-defined]
        assert id(frames["axis"]) == source_id
        assert frames["axis"] is source
        assert frames["_meta"] is meta
        assert meta == {"sentinel": ["unchanged"]}
        assert all(
            source.iloc[position, 2] is order_value
            for position, order_value in enumerate(order_values)
        )

    def test_cyclic_comparator_is_rejected_without_invocation(self) -> None:
        self._assert_rejected_before_comparison(["a", "b", "c"], _CyclicOrder)

    def test_asymmetric_comparator_is_rejected_without_invocation(self) -> None:
        self._assert_rejected_before_comparison(["a", "b"], _AsymmetricOrder)

    def test_non_transitive_comparator_is_rejected_without_invocation(self) -> None:
        self._assert_rejected_before_comparison(["a", "b", "c"], _NonTransitiveOrder)

    def test_stateful_comparator_is_rejected_without_invocation(self) -> None:
        self._assert_rejected_before_comparison(["a", "b"], _StatefulOrder)

    def test_exception_raising_comparator_is_rejected_without_invocation(self) -> None:
        self._assert_rejected_before_comparison(["a", "b"], _ExceptionRaisingOrder)

    @pytest.mark.parametrize("value", [True, 1.0, float("inf"), [1], object()])
    def test_unsupported_order_type_is_rejected_deliberately(
        self,
        value: object,
    ) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a"],
                "label": ["A"],
                "rank": [value],
            })
        }

        with pytest.raises(AxisMappingError, match="exact built-in"):
            resolve_axis_mapping(
                frames,
                _intent(
                    order_policy=AxisOrderPolicy.COLUMNS,
                    order_columns=("rank",),
                ),
            )

    def test_mixed_supported_types_in_one_order_column_are_rejected(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a", "key-b"],
                "label": ["A", "B"],
                "rank": pd.Series([1, "2"], dtype=object),
            })
        }

        with pytest.raises(AxisMappingError, match="mixed types.*int.*str"):
            resolve_axis_mapping(
                frames,
                _intent(
                    order_policy=AxisOrderPolicy.COLUMNS,
                    order_columns=("rank",),
                ),
            )

    def test_each_order_column_may_use_its_own_supported_type(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-b", "key-a", "key-c"],
                "label": ["B", "A", "C"],
                "rank": [1, 1, 1],
                "group": ["b", "a", "a"],
            })
        }

        resolved = resolve_axis_mapping(
            frames,
            _intent(
                order_policy=AxisOrderPolicy.COLUMNS,
                order_columns=("rank", "group"),
            ),
        )

        assert [member.key for member in resolved] == ["key-a", "key-c", "key-b"]

    def test_supported_ties_use_exact_canonical_key_as_final_tie_breaker(self) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-b", "key-a"],
                "label": ["B", "A"],
                "rank": [1, 1],
            })
        }

        resolved = resolve_axis_mapping(
            frames,
            _intent(
                order_policy=AxisOrderPolicy.COLUMNS,
                order_columns=("rank",),
            ),
        )

        assert [member.key for member in resolved] == ["key-a", "key-b"]


class TestCompleteNumpyIntegerVocabulary:
    def test_supported_exact_types_are_platform_complete_and_deduplicated(
        self,
    ) -> None:
        expected_types = frozenset(_NUMPY_INTEGER_ALIASES)

        supported_types = resolver_module._SUPPORTED_EXACT_NUMPY_INTEGER_TYPES
        assert frozenset(supported_types) == expected_types
        assert np.longlong in expected_types
        assert np.ulonglong in expected_types
        assert len(supported_types) == len(expected_types)
        assert len(_DISTINCT_NUMPY_INTEGER_TYPES) == len(expected_types)

    @pytest.mark.parametrize("value_type", _DISTINCT_NUMPY_INTEGER_TYPES)
    def test_every_distinct_exact_type_survives_pandas_and_orders_boundaries(
        self,
        value_type: type[np.integer],
    ) -> None:
        limits = np.iinfo(value_type)
        typed_values = np.array([limits.max, limits.min], dtype=value_type)
        frames = {
            "axis": pd.DataFrame({
                "key": ["maximum", "minimum"],
                "label": ["Maximum", "Minimum"],
                "rank": typed_values,
            })
        }

        assert type(frames["axis"].iloc[0, 2]) is value_type
        assert type(frames["axis"].iloc[1, 2]) is value_type

        resolved = resolve_axis_mapping(
            frames,
            _intent(
                order_policy=AxisOrderPolicy.COLUMNS,
                order_columns=("rank",),
            ),
        )

        assert [member.key for member in resolved] == ["minimum", "maximum"]

    @pytest.mark.parametrize("nullable_dtype", _NULLABLE_INTEGER_DTYPES)
    def test_nullable_integer_concrete_values_normalize_and_order(
        self,
        nullable_dtype: str,
    ) -> None:
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-b", "key-a"],
                "label": ["B", "A"],
                "rank": pd.Series([2, 1], dtype=nullable_dtype),
            })
        }
        extracted_type = type(frames["axis"].iloc[0, 2])

        assert extracted_type in resolver_module._SUPPORTED_EXACT_NUMPY_INTEGER_TYPES
        resolved = resolve_axis_mapping(
            frames,
            _intent(
                order_policy=AxisOrderPolicy.COLUMNS,
                order_columns=("rank",),
            ),
        )

        assert [member.key for member in resolved] == ["key-a", "key-b"]

    def test_mixed_python_and_each_numpy_integer_normalize_to_builtin_int(
        self,
    ) -> None:
        for value_type in _DISTINCT_NUMPY_INTEGER_TYPES:
            frames = {
                "axis": pd.DataFrame({
                    "key": ["key-b", "key-a"],
                    "label": ["B", "A"],
                    "rank": pd.Series([value_type(2), 1], dtype=object),
                })
            }

            resolved = resolve_axis_mapping(
                frames,
                _intent(
                    order_policy=AxisOrderPolicy.COLUMNS,
                    order_columns=("rank",),
                ),
            )

            assert [member.key for member in resolved] == ["key-a", "key-b"]

    def test_numpy_integer_subclass_is_rejected_without_conversion(self) -> None:
        value = _HostileNumpyInteger(1)
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a"],
                "label": ["A"],
                "rank": pd.Series([value], dtype=object),
            })
        }
        _HostileNumpyInteger.conversion_calls = 0

        with pytest.raises(AxisMappingError, match="unsupported value type"):
            resolve_axis_mapping(
                frames,
                _intent(
                    order_policy=AxisOrderPolicy.COLUMNS,
                    order_columns=("rank",),
                ),
            )

        assert _HostileNumpyInteger.conversion_calls == 0


class TestAdversarialExactStringsAndPhysicalLabels:
    def test_unusual_physical_label_cannot_impersonate_configured_strings(
        self,
    ) -> None:
        alias = _EqualToEveryString()
        frame = pd.DataFrame(
            [["actual"]],
            columns=pd.Index([alias], dtype=object),
        )

        with pytest.raises(
            AxisMappingError,
            match=r"missing configured column.*key.*label",
        ):
            resolve_axis_mapping({"axis": frame}, _intent())

        assert alias.string_comparisons == 0

    @pytest.mark.parametrize(
        "constructor",
        [
            lambda value: AxisMappingIntent(
                value,
                "key",
                ("label",),
                AxisOrderPolicy.SOURCE_ROW,
            ),
            lambda value: AxisMappingIntent(
                "axis",
                value,
                ("label",),
                AxisOrderPolicy.SOURCE_ROW,
            ),
            lambda value: AxisMappingIntent(
                "axis",
                "key",
                (value,),
                AxisOrderPolicy.SOURCE_ROW,
            ),
            lambda value: AxisMappingIntent(
                "axis",
                "key",
                ("label",),
                AxisOrderPolicy.COLUMNS,
                (value,),
            ),
            lambda value: ResolvedAxisMember(value, ("A",), 0),
            lambda value: ResolvedAxisMember("key", (value,), 0),
            lambda value: ResolvedAxisMapping(
                (value,),
                (ResolvedAxisMember("key", ("A",), 0),),
            ),
        ],
    )
    def test_hostile_strip_subclass_is_rejected_by_every_direct_model_boundary(
        self,
        constructor: object,
    ) -> None:
        _HostileStripString.strip_calls = 0
        value = _HostileStripString("hostile")

        with pytest.raises(AxisMappingError, match="exact built-in"):
            constructor(value)  # type: ignore[operator]

        assert _HostileStripString.strip_calls == 0

    def test_hostile_repr_subclass_never_reaches_repr_in_diagnostics(self) -> None:
        _HostileReprString.repr_calls = 0
        value = _HostileReprString("hostile")

        with pytest.raises(AxisMappingError, match="unsupported value type"):
            ResolvedAxisMember(value, ("A",), 0)

        assert _HostileReprString.repr_calls == 0

    def test_mutable_hash_subclass_is_rejected_before_hashing(self) -> None:
        _MutableHashString.hash_calls = 0
        value = _MutableHashString("key-a")

        with pytest.raises(AxisMappingError, match="exact built-in"):
            ResolvedAxisMember(value, ("A",), 0)

        assert _MutableHashString.hash_calls == 0

    def test_both_lookup_directions_reject_subclasses_without_destabilizing_mapping(
        self,
    ) -> None:
        resolved = ResolvedAxisMapping(
            ["label"],  # type: ignore[arg-type]
            [ResolvedAxisMember("key-a", ("A",), 0)],  # type: ignore[arg-type]
        )
        _MutableHashString.hash_calls = 0
        hostile_key = _MutableHashString("key-a")
        hostile_label = _MutableHashString("A")

        with pytest.raises(AxisMappingError, match="exact built-in"):
            resolved.labels_for_key(hostile_key)
        with pytest.raises(AxisMappingError, match="exact built-in"):
            resolved.key_for_labels((hostile_label,))

        hostile_key.salt = 10
        hostile_label.salt = 20
        assert _MutableHashString.hash_calls == 0
        assert resolved.labels_for_key("key-a") == ("A",)
        assert resolved.key_for_labels(("A",)) == "key-a"
        assert type(resolved.members[0].key) is str
        assert type(resolved.members[0].labels[0]) is str

    def test_source_and_used_key_subclasses_fail_without_hostile_methods(self) -> None:
        _HostileStripString.strip_calls = 0
        _HostileReprString.repr_calls = 0
        frames = {
            "axis": pd.DataFrame({
                "key": [_HostileStripString("key-a")],
                "label": ["A"],
            })
        }

        with pytest.raises(AxisMappingError, match="unsupported value type"):
            resolve_axis_mapping(frames, _intent())
        with pytest.raises(AxisMappingError, match="unsupported value type"):
            resolve_axis_mapping(
                {"axis": pd.DataFrame({"key": ["key-a"], "label": ["A"]})},
                _intent(),
                used_keys=[_HostileReprString("key-a")],
            )

        assert _HostileStripString.strip_calls == 0
        assert _HostileReprString.repr_calls == 0


class TestDiagnosticSafety:
    @pytest.mark.parametrize(
        "reject",
        [
            lambda value: AxisMappingIntent(
                value,
                "key",
                ("label",),
                AxisOrderPolicy.SOURCE_ROW,
            ),
            lambda value: AxisMappingIntent(
                "axis",
                value,
                ("label",),
                AxisOrderPolicy.SOURCE_ROW,
            ),
            lambda value: AxisMappingIntent(
                "axis",
                "key",
                (value,),
                AxisOrderPolicy.SOURCE_ROW,
            ),
            lambda value: AxisMappingIntent(
                "axis",
                "key",
                ("label",),
                AxisOrderPolicy.COLUMNS,
                (value,),
            ),
            lambda value: ResolvedAxisMember(value, ("A",), 0),
            lambda value: ResolvedAxisMember("key-a", (value,), 0),
            lambda value: ResolvedAxisMapping(
                (value,),
                (ResolvedAxisMember("key-a", ("A",), 0),),
            ),
            lambda value: ResolvedAxisMapping(
                ("label",),
                (ResolvedAxisMember("key-a", ("A",), 0),),
            ).labels_for_key(value),
            lambda value: ResolvedAxisMapping(
                ("label",),
                (ResolvedAxisMember("key-a", ("A",), 0),),
            ).key_for_labels((value,)),
        ],
    )
    def test_direct_boundaries_do_not_read_hostile_type_names(
        self,
        reject: object,
    ) -> None:
        global _hostile_type_name_calls
        global _hostile_type_hash_calls
        global _hostile_type_equality_calls
        _hostile_type_name_calls = 0
        _hostile_type_hash_calls = 0
        _hostile_type_equality_calls = 0

        with pytest.raises(AxisMappingError, match="unsupported value type"):
            reject(_HostileType())  # type: ignore[operator]

        assert _hostile_type_name_calls == 0
        assert _hostile_type_hash_calls == 0
        assert _hostile_type_equality_calls == 0

    @pytest.mark.parametrize(
        "reject",
        [
            lambda value: resolve_axis_mapping(
                {
                    "axis": pd.DataFrame({
                        "key": pd.Series([value], dtype=object),
                        "label": ["A"],
                    })
                },
                _intent(),
            ),
            lambda value: resolve_axis_mapping(
                {
                    "axis": pd.DataFrame({
                        "key": ["key-a"],
                        "label": pd.Series([value], dtype=object),
                    })
                },
                _intent(),
            ),
            lambda value: resolve_axis_mapping(
                {"axis": pd.DataFrame({"key": ["key-a"], "label": ["A"]})},
                _intent(),
                used_keys=[value],
            ),
            lambda value: resolve_axis_mapping(
                {
                    "axis": pd.DataFrame({
                        "key": ["key-a"],
                        "label": ["A"],
                        "rank": pd.Series([value], dtype=object),
                    })
                },
                _intent(
                    order_policy=AxisOrderPolicy.COLUMNS,
                    order_columns=("rank",),
                ),
            ),
        ],
    )
    def test_resolver_boundaries_do_not_read_hostile_type_names(
        self,
        reject: object,
    ) -> None:
        global _hostile_type_name_calls
        global _hostile_type_hash_calls
        global _hostile_type_equality_calls
        _hostile_type_name_calls = 0
        _hostile_type_hash_calls = 0
        _hostile_type_equality_calls = 0

        with pytest.raises(AxisMappingError, match="unsupported value type"):
            reject(_HostileType())  # type: ignore[operator]

        assert _hostile_type_name_calls == 0
        assert _hostile_type_hash_calls == 0
        assert _hostile_type_equality_calls == 0


class TestExactVisibleLabelTuples:
    @pytest.mark.parametrize(
        "reject",
        [
            lambda labels: ResolvedAxisMember("key-a", labels, 0),
            lambda labels: ResolvedAxisMapping(
                ("label",),
                (_forge_member_with_labels(labels),),
            ),
            lambda labels: ResolvedAxisMapping(
                ("label",),
                (ResolvedAxisMember("key-a", ("A",), 0),),
            ).key_for_labels(labels),
        ],
    )
    def test_tuple_subclasses_are_rejected_before_hostile_methods(
        self,
        reject: object,
    ) -> None:
        labels = _HostileMutableTuple(("A",))
        _HostileMutableTuple.reset_calls()

        with pytest.raises(AxisMappingError, match="exact built-in tuple"):
            reject(labels)  # type: ignore[operator]

        assert _HostileMutableTuple.len_calls == 0
        assert _HostileMutableTuple.iteration_calls == 0
        assert _HostileMutableTuple.hash_calls == 0
        assert _HostileMutableTuple.equality_calls == 0
        assert _HostileMutableTuple.repr_calls == 0

        labels.salt = 100
        stable = ResolvedAxisMapping(
            ("label",),
            (ResolvedAxisMember("key-a", ("A",), 0),),
        )
        assert stable.labels_for_key("key-a") == ("A",)
        assert stable.key_for_labels(("A",)) == "key-a"

    def test_direct_and_resolved_labels_use_only_exact_builtin_tuples(self) -> None:
        direct = ResolvedAxisMapping(
            ("label",),
            (ResolvedAxisMember("key-a", ("A",), 0),),
        )
        resolved = resolve_axis_mapping(
            {"axis": pd.DataFrame({"key": ["key-b"], "label": ["B"]})},
            _intent(),
        )

        for mapping in (direct, resolved):
            assert type(mapping.members[0].labels) is tuple
            assert type(mapping.labels_for_key(mapping.members[0].key)) is tuple
            assert all(type(labels) is tuple for labels in mapping._key_by_labels)


class TestDirectModelConstruction:
    def test_positions_must_be_exact_contiguous_zero_based_integers(self) -> None:
        with pytest.raises(AxisMappingError, match="exact built-in integer"):
            ResolvedAxisMember("key", ("A",), True)
        with pytest.raises(AxisMappingError, match="start at zero"):
            ResolvedAxisMapping(
                ("label",),
                (ResolvedAxisMember("key", ("A",), 1),),
            )

    def test_wrong_arity_and_duplicate_members_fail_directly(self) -> None:
        with pytest.raises(AxisMappingError, match="arity 2; expected 1"):
            ResolvedAxisMapping(
                ("label",),
                (ResolvedAxisMember("key", ("A", "B"), 0),),
            )
        with pytest.raises(AxisMappingError, match="duplicate canonical key"):
            ResolvedAxisMapping(
                ("label",),
                (
                    ResolvedAxisMember("key", ("A",), 0),
                    ResolvedAxisMember("key", ("B",), 1),
                ),
            )
        with pytest.raises(AxisMappingError, match="duplicate complete"):
            ResolvedAxisMapping(
                ("label",),
                (
                    ResolvedAxisMember("key-a", ("A",), 0),
                    ResolvedAxisMember("key-b", ("A",), 1),
                ),
            )

    def test_ordered_iterables_are_copied_and_unordered_containers_rejected(
        self,
    ) -> None:
        labels = ["label"]
        members = [ResolvedAxisMember("key", ("A",), 0)]
        resolved = ResolvedAxisMapping(labels, (member for member in members))  # type: ignore[arg-type]

        labels[0] = "changed"
        members.clear()
        assert resolved.label_columns == ("label",)
        assert resolved.members == (ResolvedAxisMember("key", ("A",), 0),)

        with pytest.raises(AxisMappingError, match="ordered iterable"):
            ResolvedAxisMapping(("label",), {ResolvedAxisMember("key", ("A",), 0)})  # type: ignore[arg-type]

    def test_derived_maps_are_equal_when_members_are_equal(self) -> None:
        first = ResolvedAxisMapping(
            ("label",),
            (ResolvedAxisMember("key", ("A",), 0),),
        )
        second = ResolvedAxisMapping(
            ["label"],  # type: ignore[arg-type]
            [ResolvedAxisMember("key", ("A",), 0)],  # type: ignore[arg-type]
        )

        assert first == second
        assert first.labels_for_key("key") == second.labels_for_key("key")
        assert first.key_for_labels(("A",)) == second.key_for_labels(("A",))


class TestNarrowExceptionTranslation:
    def test_unrelated_physical_helper_defect_is_not_relabelled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail_with_programming_defect(*args: object, **kwargs: object) -> None:
            raise AssertionError("simulated helper defect")

        monkeypatch.setattr(
            resolver_module,
            "ensure_unique_physical_column_labels",
            fail_with_programming_defect,
        )
        frames = {
            "axis": pd.DataFrame({
                "key": ["key-a"],
                "label": ["A"],
            })
        }

        with pytest.raises(AssertionError, match="simulated helper defect"):
            resolve_axis_mapping(frames, _intent())


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
        with pytest.raises(AxisMappingError, match="exact built-in tuple"):
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
