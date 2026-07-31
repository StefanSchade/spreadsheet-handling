"""Contract tests for the GX-2 grouped-XRef composites.

GX-2 of ``FTR-XREF-AXIS-MAPPINGS-P4A2``. These prove the two public composites
(`contract_grouped_xref` / `expand_grouped_xref`) compose unchanged XRef with the
accepted GX-1 primitives around the trusted `GroupedMatrix` carrier: exact dense
roundtrip, single mapping resolution with forward completeness, structural
pairing safety, XRef-owned metadata, `drop_source` atomicity, and safe
composite diagnostics. XRef shape conversion and the resolver bijection are proven
elsewhere and relied upon here, not reasserted.
"""
from __future__ import annotations

import copy
import inspect
from unittest.mock import patch

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.xref_axis_mapping import (
    AxisMappingError,
    AxisMappingIntent,
    AxisOrderPolicy,
    ResolvedAxisMapping,
    resolve_axis_mapping,
)
from spreadsheet_handling.domain.transformations.grouped_xref import (
    DynamicColumn,
    GroupedHeader,
    GroupedHeaderError,
    GroupedMatrix,
    GroupedXrefError,
    RowKeyColumn,
    contract_grouped_xref,
    expand_grouped_xref,
    grouped_matrix_from_canonical,
)
import spreadsheet_handling.domain.transformations.grouped_xref.composites as composites

pytestmark = pytest.mark.ftr("FTR-XREF-AXIS-MAPPINGS-P4A2")


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

_KEYS2 = ("credit.annuity_loan", "credit.fixed_rate_loan", "deposit.balance")


def _dense_relation(row_ids: tuple[str, ...] = ("r1", "r2")) -> pd.DataFrame:
    """A *dense* relation: every (row, key) pair present, so the contract/expand
    roundtrip is exact (no XRef ``fill_value`` densification of missing cells)."""
    rows = [
        {"row_id": rid, "column_key": key, "value": f"{rid}:{key}"}
        for rid in row_ids
        for key in _KEYS2
    ]
    return pd.DataFrame(rows)


def _dense_relation_two_row_keys() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "rk1": rk1,
                "rk2": rk2,
                "column_key": key,
                "value": f"{rk1}:{rk2}:{key}",
            }
            for rk1, rk2 in (("a", "x"), ("b", "y"))
            for key in _KEYS2
        ]
    )


def _source2() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "key": list(_KEYS2),
            "grp": ["Kredit", "Kredit", "Einlage"],
            "leaf": ["Annuitätendarlehen", "Festzinsdarlehen", "Guthaben"],
        }
    )


def _frames() -> dict[str, object]:
    return {"rel": _dense_relation(), "src": _source2()}


def _mapping(source: pd.DataFrame | None = None) -> ResolvedAxisMapping:
    frames = {"src": _source2() if source is None else source}
    return resolve_axis_mapping(
        frames,
        AxisMappingIntent(
            source_frame="src",
            key_column="key",
            label_columns=("grp", "leaf"),
            order_policy=AxisOrderPolicy.SOURCE_ROW,
        ),
    )


def _forward(frames: dict[str, object], **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = dict(
        relation="rel",
        output="mtx",
        row_keys="row_id",
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    kwargs.update(overrides)
    return contract_grouped_xref(frames, **kwargs)  # type: ignore[arg-type]


def _sorted(relation: pd.DataFrame) -> pd.DataFrame:
    return relation.sort_values(["row_id", "column_key"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# GroupedMatrix carrier                                                        #
# --------------------------------------------------------------------------- #

def test_carrier_direct_construction_is_rejected_deliberately() -> None:
    header = GroupedHeader(
        level_names=("grp", "leaf"),
        columns=(RowKeyColumn(label="row_id", position=0),),
    )
    with pytest.raises(GroupedXrefError, match="grouped_matrix_from_canonical"):
        GroupedMatrix(frame=pd.DataFrame({"row_id": [1]}), header=header)


def test_public_factory_validates_frame_and_header_types() -> None:
    header = GroupedHeader(
        level_names=("grp", "leaf"),
        columns=(RowKeyColumn(label="row_id", position=0),),
    )
    with pytest.raises(GroupedXrefError):
        grouped_matrix_from_canonical(  # type: ignore[arg-type]
            [1, 2, 3], header, mapping=_mapping()
        )
    with pytest.raises(GroupedXrefError):
        grouped_matrix_from_canonical(  # type: ignore[arg-type]
            pd.DataFrame({"row_id": [1]}), object(), mapping=_mapping()
        )


def test_carrier_has_identity_semantics_not_value_equality() -> None:
    produced = _forward(_frames())["mtx"]
    assert isinstance(produced, GroupedMatrix)
    a = grouped_matrix_from_canonical(
        produced.frame,
        produced.header,
        mapping=_mapping(),
    )
    b = grouped_matrix_from_canonical(
        produced.frame,
        produced.header,
        mapping=_mapping(),
    )
    # Same content, distinct instances: NOT equal (identity semantics, not a
    # value object), and hashable only by identity.
    assert a == a
    assert a != b
    assert hash(a) == hash(a)
    assert hash(a) != hash(b)


def test_public_factory_accepts_exact_canonical_pair_for_future_carriers() -> None:
    produced = _forward(_frames())["mtx"]
    assert isinstance(produced, GroupedMatrix)
    rebuilt = grouped_matrix_from_canonical(
        produced.frame,
        produced.header,
        mapping=_mapping(),
    )
    assert rebuilt.frame is produced.frame
    assert rebuilt.header is produced.header


def test_public_factory_allows_cell_edits_with_unchanged_schema() -> None:
    produced = _forward(_frames())["mtx"]
    assert isinstance(produced, GroupedMatrix)
    edited = produced.frame.copy()
    edited.loc[0, _KEYS2[0]] = "edited"
    rebuilt = grouped_matrix_from_canonical(
        edited,
        produced.header,
        mapping=_mapping(),
    )
    assert rebuilt.frame.loc[0, _KEYS2[0]] == "edited"


def test_public_factory_rejects_reordered_dynamic_columns() -> None:
    produced = _forward(_frames())["mtx"]
    assert isinstance(produced, GroupedMatrix)
    foreign = produced.frame[["row_id", _KEYS2[1], _KEYS2[0], _KEYS2[2]]]
    with pytest.raises(GroupedXrefError, match="pairing does not match"):
        grouped_matrix_from_canonical(
            foreign,
            produced.header,
            mapping=_mapping(),
        )


def test_public_factory_rejects_moved_row_key() -> None:
    produced = _forward(_frames())["mtx"]
    assert isinstance(produced, GroupedMatrix)
    foreign = produced.frame[[_KEYS2[0], "row_id", _KEYS2[1], _KEYS2[2]]]
    with pytest.raises(GroupedXrefError, match="pairing does not match"):
        grouped_matrix_from_canonical(
            foreign,
            produced.header,
            mapping=_mapping(),
        )


def test_public_factory_rejects_unrelated_same_width_frame() -> None:
    produced = _forward(_frames())["mtx"]
    assert isinstance(produced, GroupedMatrix)
    unrelated_source = pd.DataFrame(
        {
            "key": ["other.1", "other.2", "other.3"],
            "grp": ["Other", "Other", "Other"],
            "leaf": ["One", "Two", "Three"],
        }
    )
    unrelated = produced.frame.copy()
    unrelated.columns = ["row_id", "other.1", "other.2", "other.3"]
    with pytest.raises(GroupedXrefError, match="pairing does not match"):
        grouped_matrix_from_canonical(
            unrelated,
            produced.header,
            mapping=_mapping(unrelated_source),
        )


def test_public_factory_rejects_stale_header_after_mapping_label_change() -> None:
    produced = _forward(_frames())["mtx"]
    assert isinstance(produced, GroupedMatrix)
    changed = _source2()
    changed.loc[changed["key"] == _KEYS2[0], "leaf"] = "Changed"
    with pytest.raises(GroupedXrefError, match="pairing does not match"):
        grouped_matrix_from_canonical(
            produced.frame,
            produced.header,
            mapping=_mapping(changed),
        )


def test_public_factory_rejects_multiindex_and_altered_headers() -> None:
    produced = _forward(_frames())["mtx"]
    assert isinstance(produced, GroupedMatrix)
    multiindex = produced.frame.copy()
    multiindex.columns = pd.MultiIndex.from_tuples(
        [("row_id", ""), *((key, "") for key in _KEYS2)]
    )
    with pytest.raises(GroupedHeaderError, match="MultiIndex"):
        grouped_matrix_from_canonical(
            multiindex,
            produced.header,
            mapping=_mapping(),
        )

    altered = produced.frame.copy()
    altered.columns = ["row_id", "unknown", _KEYS2[1], _KEYS2[2]]
    with pytest.raises(AxisMappingError, match="Unknown canonical axis key"):
        grouped_matrix_from_canonical(
            altered,
            produced.header,
            mapping=_mapping(),
        )


# --------------------------------------------------------------------------- #
# Forward composite                                                            #
# --------------------------------------------------------------------------- #

def test_forward_publishes_one_grouped_matrix_with_exact_descriptor() -> None:
    frames = _frames()
    out = _forward(frames, level_names=["Kategorie", "Produkt"])
    grouped = out["mtx"]
    assert isinstance(grouped, GroupedMatrix)
    header = grouped.header
    assert header.level_names == ("Kategorie", "Produkt")
    # row-key column first, then one dynamic column per canonical key in matrix order
    assert type(header.columns[0]) is RowKeyColumn
    dynamic = {c.labels for c in header.columns if type(c) is DynamicColumn}
    assert dynamic == {
        ("Kredit", "Annuitätendarlehen"),
        ("Kredit", "Festzinsdarlehen"),
        ("Einlage", "Guthaben"),
    }


def test_forward_flat_frame_keeps_canonical_string_headers() -> None:
    out = _forward(_frames())
    flat = out["mtx"].frame
    assert list(flat.columns) == ["row_id", *_KEYS2]
    assert not isinstance(flat.columns, pd.MultiIndex)


def test_forward_introduces_no_private_frame() -> None:
    frames = _frames()
    out = _forward(frames)
    assert set(out) == {"rel", "src", "mtx", "_meta"}


def test_forward_does_not_mutate_caller_frames_or_meta() -> None:
    frames = _frames()
    snapshot = copy.deepcopy(frames)
    _forward(frames)
    assert set(frames) == {"rel", "src"}
    assert "_meta" not in frames
    for name, df in snapshot.items():
        pd.testing.assert_frame_equal(frames[name], df)


def test_forward_used_keys_completeness_rejects_missing_source_key() -> None:
    frames = _frames()
    # Drop a canonical key from the source so a matrix dynamic header is missing.
    frames["src"] = _source2().iloc[:2].reset_index(drop=True)
    with pytest.raises(AxisMappingError):
        _forward(frames)


def test_forward_missing_source_frame_rejected() -> None:
    frames = {"rel": _dense_relation()}
    with pytest.raises(AxisMappingError):
        _forward(frames)


def test_forward_rejects_drop_source_into_same_output() -> None:
    with pytest.raises(GroupedXrefError):
        _forward(_frames(), output="rel", drop_source=True)


@pytest.mark.parametrize("shape", ["list", "tuple", "generator"])
def test_forward_owns_multiple_row_keys_for_every_iterable_shape(shape: str) -> None:
    declarations: object
    if shape == "list":
        declarations = ["rk1", "rk2"]
    elif shape == "tuple":
        declarations = ("rk1", "rk2")
    else:
        declarations = (key for key in ("rk1", "rk2"))
    out = contract_grouped_xref(
        {"rel": _dense_relation_two_row_keys(), "src": _source2()},
        relation="rel",
        output="mtx",
        row_keys=declarations,  # type: ignore[arg-type]
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    grouped = out["mtx"]
    assert isinstance(grouped, GroupedMatrix)
    assert list(grouped.frame.columns[:2]) == ["rk1", "rk2"]


def test_forward_consumes_one_shot_row_keys_once_and_reuses_owned_tuple() -> None:
    class OneShotRowKeys:
        def __init__(self) -> None:
            self.iterations = 0

        def __iter__(self):  # type: ignore[no-untyped-def]
            self.iterations += 1
            if self.iterations > 1:
                raise AssertionError("row_keys was iterated more than once")
            return iter(("rk1", "rk2"))

    declaration = OneShotRowKeys()
    with (
        patch.object(
            composites,
            "contract_xref",
            wraps=composites.contract_xref,
        ) as xref_spy,
        patch.object(
            composites,
            "build_grouped_header",
            wraps=composites.build_grouped_header,
        ) as header_spy,
        patch.object(
            composites,
            "resolve_axis_mapping",
            wraps=composites.resolve_axis_mapping,
        ) as resolver_spy,
    ):
        contract_grouped_xref(
            {"rel": _dense_relation_two_row_keys(), "src": _source2()},
            relation="rel",
            output="mtx",
            row_keys=declaration,
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )

    assert declaration.iterations == 1
    xref_row_keys = xref_spy.call_args.kwargs["row_keys"]
    header_row_keys = header_spy.call_args.kwargs["row_keys"]
    assert xref_row_keys is header_row_keys
    assert xref_row_keys == ("rk1", "rk2")
    assert resolver_spy.call_count == 1
    assert resolver_spy.call_args.kwargs["used_keys"] == list(_KEYS2)


@pytest.mark.parametrize("invalid", [b"rk1", bytearray(b"rk1"), 42])
def test_row_key_container_shape_failures_are_safe(invalid: object) -> None:
    with pytest.raises(GroupedXrefError, match="row_keys must be"):
        contract_grouped_xref(
            _frames(),
            relation="rel",
            output="mtx",
            row_keys=invalid,  # type: ignore[arg-type]
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )


def test_duplicate_row_key_semantics_remain_owned_by_xref() -> None:
    with pytest.raises(ValueError, match="row_keys contains duplicate field"):
        contract_grouped_xref(
            {"rel": _dense_relation_two_row_keys(), "src": _source2()},
            relation="rel",
            output="mtx",
            row_keys=(key for key in ("rk1", "rk1")),
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )


# --------------------------------------------------------------------------- #
# Metadata / name ownership                                                    #
# --------------------------------------------------------------------------- #

def test_forward_metadata_is_xref_owned_with_public_names_only() -> None:
    out = _forward(_frames())
    meta = out["_meta"]
    # No grouped-XRef metadata root; only XRef's own root.
    assert set(meta) == {"xref_crosstable"}
    configs = meta["xref_crosstable"]
    assert set(configs) == {"rel"}  # config id == relation when name is None
    payload = configs["rel"]
    assert payload["relation"] == "rel" and payload["matrix"] == "mtx"
    # Only caller-supplied public frame names appear.
    assert "mtx" in (payload["matrix"],)


def test_forward_xref_config_id_becomes_xref_config_id() -> None:
    out = _forward(_frames(), xref_config_id="my_axis")
    assert set(out["_meta"]["xref_crosstable"]) == {"my_axis"}


def test_xref_config_id_requires_exact_non_empty_string() -> None:
    with pytest.raises(GroupedXrefError, match="xref_config_id"):
        _forward(_frames(), xref_config_id=" ")
    with pytest.raises(GroupedXrefError, match="xref_config_id"):
        _forward(_frames(), xref_config_id=1)


# --------------------------------------------------------------------------- #
# Atomicity                                                                    #
# --------------------------------------------------------------------------- #

def test_failure_after_xref_before_publication_leaves_caller_unchanged() -> None:
    frames = _frames()
    snapshot = copy.deepcopy(frames)
    # ``level_names`` of the wrong length fails inside build_grouped_header, i.e.
    # strictly after contract_xref produced its (discardable) interim copy.
    with pytest.raises(GroupedHeaderError):
        _forward(frames, level_names=["only_one_level"])
    assert set(frames) == {"rel", "src"}
    assert "_meta" not in frames
    for name, df in snapshot.items():
        pd.testing.assert_frame_equal(frames[name], df)


# --------------------------------------------------------------------------- #
# Inverse composite                                                            #
# --------------------------------------------------------------------------- #

def test_inverse_restores_canonical_relation_exact_dense_roundtrip() -> None:
    frames = _frames()
    forward = _forward(frames)
    inverse = expand_grouped_xref(
        {"mtx": forward["mtx"], "src": frames["src"]},
        matrix="mtx",
        output="rel_out",
        row_keys="row_id",
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    pd.testing.assert_frame_equal(
        _sorted(inverse["rel_out"]), _sorted(_dense_relation())
    )


@pytest.mark.parametrize("shape", ["string", "list", "tuple", "generator"])
def test_inverse_owns_row_keys_once_for_every_iterable_shape(shape: str) -> None:
    if shape == "string":
        forward_row_keys: object = "row_id"
        inverse_row_keys: object = "row_id"
    elif shape == "list":
        forward_row_keys = ["row_id"]
        inverse_row_keys = ["row_id"]
    elif shape == "tuple":
        forward_row_keys = ("row_id",)
        inverse_row_keys = ("row_id",)
    else:
        forward_row_keys = (key for key in ("row_id",))
        inverse_row_keys = (key for key in ("row_id",))
    frames = _frames()
    forward = _forward(frames, row_keys=forward_row_keys)
    inverse = expand_grouped_xref(
        {"mtx": forward["mtx"], "src": frames["src"]},
        matrix="mtx",
        output="rel_out",
        row_keys=inverse_row_keys,  # type: ignore[arg-type]
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    pd.testing.assert_frame_equal(
        _sorted(inverse["rel_out"]),
        _sorted(_dense_relation()),
    )


def test_inverse_accepts_one_shot_two_row_key_generator() -> None:
    relation = _dense_relation_two_row_keys()
    forward = contract_grouped_xref(
        {"rel": relation, "src": _source2()},
        relation="rel",
        output="mtx",
        row_keys=["rk1", "rk2"],
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    inverse = expand_grouped_xref(
        {"mtx": forward["mtx"], "src": _source2()},
        matrix="mtx",
        output="rel_out",
        row_keys=(key for key in ("rk1", "rk2")),
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    pd.testing.assert_frame_equal(
        inverse["rel_out"].sort_values(["rk1", "rk2", "column_key"]).reset_index(drop=True),
        relation.sort_values(["rk1", "rk2", "column_key"]).reset_index(drop=True),
    )


def test_inverse_requires_grouped_matrix_carrier() -> None:
    frames = {"mtx": _dense_relation(), "src": _source2()}
    with pytest.raises(GroupedXrefError):
        expand_grouped_xref(
            frames,
            matrix="mtx",
            output="rel_out",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )


def test_inverse_missing_matrix_frame_rejected() -> None:
    with pytest.raises(GroupedXrefError):
        expand_grouped_xref(
            {"src": _source2()},
            matrix="mtx",
            output="rel_out",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )


def test_inverse_exposes_no_descriptor_parameter() -> None:
    params = set(inspect.signature(expand_grouped_xref).parameters)
    assert "header" not in params
    assert "descriptor" not in params
    assert "grouped_header" not in params


def test_grouped_signatures_use_xref_config_id_not_name() -> None:
    for function in (contract_grouped_xref, expand_grouped_xref):
        params = set(inspect.signature(function).parameters)
        assert "xref_config_id" in params
        assert "name" not in params


def test_inverse_keeps_grouped_matrix_when_not_dropping_source() -> None:
    frames = _frames()
    forward = _forward(frames)
    inverse = expand_grouped_xref(
        {"mtx": forward["mtx"], "src": frames["src"]},
        matrix="mtx",
        output="rel_out",
        row_keys="row_id",
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
    )
    # The grouped representation is preserved under ``matrix`` (not the transient
    # unwrapped flat frame).
    assert isinstance(inverse["mtx"], GroupedMatrix)


def test_mapping_drift_between_forward_and_inverse_is_rejected() -> None:
    frames = _frames()
    forward = _forward(frames)
    # The source changes one leaf label after the grouped matrix was built; the
    # descriptor still carries the old visible tuple, which no longer resolves.
    drifted = _source2()
    drifted.loc[drifted["key"] == "deposit.balance", "leaf"] = "Sichteinlage"
    with pytest.raises(GroupedXrefError, match="pairing does not match"):
        expand_grouped_xref(
            {"mtx": forward["mtx"], "src": drifted},
            matrix="mtx",
            output="rel_out",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )


def test_inverse_revalidates_pair_after_dataframe_column_mutation() -> None:
    frames = _frames()
    forward = _forward(frames)
    grouped = forward["mtx"]
    assert isinstance(grouped, GroupedMatrix)
    grouped.frame.columns = [
        "row_id",
        _KEYS2[1],
        _KEYS2[0],
        _KEYS2[2],
    ]
    caller = {"mtx": grouped, "src": frames["src"]}
    with pytest.raises(GroupedXrefError, match="pairing does not match"):
        expand_grouped_xref(
            caller,
            matrix="mtx",
            output="rel_out",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )
    assert set(caller) == {"mtx", "src"}
    assert "_meta" not in caller


def test_inverse_rejects_moved_row_key_before_expansion() -> None:
    frames = _frames()
    grouped = _forward(frames)["mtx"]
    assert isinstance(grouped, GroupedMatrix)
    grouped.frame.columns = [
        _KEYS2[0],
        "row_id",
        _KEYS2[1],
        _KEYS2[2],
    ]
    caller = {"mtx": grouped, "src": frames["src"]}
    with pytest.raises(GroupedXrefError, match="pairing does not match"):
        expand_grouped_xref(
            caller,
            matrix="mtx",
            output="rel_out",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )
    assert "rel_out" not in caller


def test_inverse_rejects_multiindex_and_altered_headers_before_expansion() -> None:
    frames = _frames()
    grouped = _forward(frames)["mtx"]
    assert isinstance(grouped, GroupedMatrix)
    grouped.frame.columns = pd.MultiIndex.from_tuples(
        [("row_id", ""), *((key, "") for key in _KEYS2)]
    )
    with pytest.raises(GroupedHeaderError, match="MultiIndex"):
        expand_grouped_xref(
            {"mtx": grouped, "src": frames["src"]},
            matrix="mtx",
            output="rel_out",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )

    grouped = _forward(frames)["mtx"]
    assert isinstance(grouped, GroupedMatrix)
    grouped.frame.columns = ["row_id", "unknown", _KEYS2[1], _KEYS2[2]]
    with pytest.raises(AxisMappingError, match="Unknown canonical axis key"):
        expand_grouped_xref(
            {"mtx": grouped, "src": frames["src"]},
            matrix="mtx",
            output="rel_out",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )


def test_inverse_xref_config_id_becomes_xref_config_id() -> None:
    frames = _frames()
    forward = _forward(frames)
    inverse = expand_grouped_xref(
        {"mtx": forward["mtx"], "src": frames["src"]},
        matrix="mtx",
        output="rel_out",
        row_keys="row_id",
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
        xref_config_id="my_inverse_axis",
    )
    assert set(inverse["_meta"]["xref_crosstable"]) == {"my_inverse_axis"}


def test_inverse_resolves_mapping_exactly_once_for_pair_check_and_restore() -> None:
    frames = _frames()
    forward = _forward(frames)
    with patch.object(
        composites,
        "resolve_axis_mapping",
        wraps=composites.resolve_axis_mapping,
    ) as resolver_spy:
        expand_grouped_xref(
            {"mtx": forward["mtx"], "src": frames["src"]},
            matrix="mtx",
            output="rel_out",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
        )
    assert resolver_spy.call_count == 1
    assert "used_keys" not in resolver_spy.call_args.kwargs


def test_inverse_rejects_drop_source_into_same_output() -> None:
    frames = _frames()
    forward = _forward(frames)
    with pytest.raises(GroupedXrefError):
        expand_grouped_xref(
            {"mtx": forward["mtx"], "src": frames["src"]},
            matrix="mtx",
            output="mtx",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
            drop_source=True,
        )


# --------------------------------------------------------------------------- #
# drop_source                                                                  #
# --------------------------------------------------------------------------- #

def test_forward_drop_source_marks_relation_for_cleanup() -> None:
    out = _forward(_frames(), drop_source=True)
    assert out["_meta"]["pipeline_cleanup"]["drop_frames"] == ["rel"]


def test_inverse_drop_source_marks_matrix_for_cleanup() -> None:
    frames = _frames()
    forward = _forward(frames)
    inverse = expand_grouped_xref(
        {"mtx": forward["mtx"], "src": frames["src"]},
        matrix="mtx",
        output="rel_out",
        row_keys="row_id",
        source_frame="src",
        key_column="key",
        label_columns=["grp", "leaf"],
        drop_source=True,
    )
    assert inverse["_meta"]["pipeline_cleanup"]["drop_frames"] == ["mtx"]


# --------------------------------------------------------------------------- #
# Order policy independence                                                    #
# --------------------------------------------------------------------------- #

def test_roundtrip_identical_under_both_order_policies() -> None:
    def run(order_policy: str, order_columns: tuple[str, ...]) -> pd.DataFrame:
        source = _source2()
        source["ord"] = [2, 1, 3]
        frames = {"rel": _dense_relation(), "src": source}
        forward = contract_grouped_xref(
            frames,
            relation="rel",
            output="mtx",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
            order_policy=order_policy,
            order_columns=order_columns,
        )
        inverse = expand_grouped_xref(
            {"mtx": forward["mtx"], "src": source},
            matrix="mtx",
            output="rel_out",
            row_keys="row_id",
            source_frame="src",
            key_column="key",
            label_columns=["grp", "leaf"],
            order_policy=order_policy,
            order_columns=order_columns,
        )
        return _sorted(inverse["rel_out"])

    by_row = run("source_row", ())
    by_cols = run("columns", ("ord",))
    pd.testing.assert_frame_equal(by_row, by_cols)
    pd.testing.assert_frame_equal(by_row, _sorted(_dense_relation()))


# --------------------------------------------------------------------------- #
# Arity 3, repeated upper levels, literal delimiters                          #
# --------------------------------------------------------------------------- #

def test_roundtrip_arity_three_repeated_upper_and_literal_delimiters() -> None:
    keys = ("k.a", "k.b", "k.c")
    # Repeated upper/middle labels with distinct complete tuples, and literal
    # " / " and "." inside components -- must survive with no split/join.
    source = pd.DataFrame(
        {
            "key": list(keys),
            "top": ["Group / One", "Group / One", "Group / Two"],
            "mid": ["M.1", "M.1", "M.2"],
            "leaf": ["Leaf A", "Leaf B", "Leaf C"],
        }
    )
    relation = pd.DataFrame(
        [
            {"row_id": rid, "column_key": key, "value": f"{rid}:{key}"}
            for rid in ("r1", "r2")
            for key in keys
        ]
    )
    frames = {"rel": relation, "src": source}
    forward = contract_grouped_xref(
        frames,
        relation="rel",
        output="mtx",
        row_keys="row_id",
        source_frame="src",
        key_column="key",
        label_columns=["top", "mid", "leaf"],
    )
    header = forward["mtx"].header
    assert header.arity == 3
    labels = {c.labels for c in header.columns if type(c) is DynamicColumn}
    assert ("Group / One", "M.1", "Leaf A") in labels
    assert ("Group / One", "M.1", "Leaf B") in labels
    inverse = expand_grouped_xref(
        {"mtx": forward["mtx"], "src": source},
        matrix="mtx",
        output="rel_out",
        row_keys="row_id",
        source_frame="src",
        key_column="key",
        label_columns=["top", "mid", "leaf"],
    )
    pd.testing.assert_frame_equal(
        _sorted(inverse["rel_out"]),
        relation.sort_values(["row_id", "column_key"]).reset_index(drop=True),
    )
