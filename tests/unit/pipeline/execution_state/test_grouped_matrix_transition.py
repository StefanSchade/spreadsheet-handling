"""Standalone GroupedMatrix introduction and disjoint-role locality.

FTR section 10; test matrix items B (standalone GroupedMatrix introduction),
E (two disjoint GroupedMatrix introductions), and F (locality collision
rejection). Also covers the independent E4 implementation review's Blocking
F3 finding: the footprint must include every genuinely frame-valued
configuration key, not only `relation`/`table`/`output`.
"""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.grouped_xref import contract_grouped_xref
from spreadsheet_handling.domain.transformations.xref_axis_mapping import AxisMappingError
from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    ExpandGroupedCertificate,
    GroupedMatrixRole,
    GroupedProducerCertificate,
    TransitionEffect,
    Uncertified,
    classify_expand_grouped_step,
    classify_grouped_producer_step,
    disjoint_grouped_introduction,
    grouped_matrix_role,
)
from spreadsheet_handling.pipeline.types import BoundFramesTargetCall

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _contract_step(**overrides: object):
    config = {
        "relation": "source",
        "output": "grouped",
        "row_keys": ["variable_id"],
        "source_frame": "variables",
        "key_column": "variable_id",
        "label_columns": ["group"],
        "value": "value",
    }
    config.update(overrides)
    return build_steps_from_config([{"step": "contract_grouped_xref", **config}])[0]


def _reconstruct_step(**overrides: object):
    config = {
        "table": "parsed",
        "output": "grouped",
        "row_keys": ["variable_id"],
        "source_frame": "variables",
        "key_column": "variable_id",
        "label_columns": ["group"],
    }
    config.update(overrides)
    return build_steps_from_config([{"step": "reconstruct_grouped_matrix", **config}])[0]


def _expand_step(**overrides: object):
    config = {
        "matrix": "grouped",
        "output": "expanded",
        "row_keys": ["variable_id"],
        "source_frame": "variables",
        "key_column": "variable_id",
        "label_columns": ["group"],
        "column_key": "column_key",
        "value": "value",
    }
    config.update(overrides)
    return build_steps_from_config([{"step": "expand_grouped_xref", **config}])[0]


class _MutableFill:
    def __init__(self, marker: str) -> None:
        self.marker = marker


class _MutableNames:
    def __init__(self, *names: str) -> None:
        self.names = list(names)

    def __iter__(self):
        return iter(self.names)


def test_contract_grouped_xref_produces_the_expected_descriptor() -> None:
    certificate = classify_grouped_producer_step(_contract_step())
    assert certificate == GroupedProducerCertificate(
        producer="contract_grouped_xref",
        output="grouped",
        source="source",
        source_frame="variables",
        value_column="value",
        drop_source=False,
        row_keys=("variable_id",),
    )
    role = grouped_matrix_role(certificate)
    assert role == GroupedMatrixRole(
        frame="grouped", producer="contract_grouped_xref", source="source",
        effect=TransitionEffect.INTRODUCE,
    )


def test_reconstruct_grouped_matrix_produces_the_expected_descriptor() -> None:
    certificate = classify_grouped_producer_step(_reconstruct_step())
    assert certificate == GroupedProducerCertificate(
        producer="reconstruct_grouped_matrix",
        output="grouped",
        source="parsed",
        source_frame="variables",
        value_column=None,
        drop_source=False,
        row_keys=("variable_id",),
    )


def test_unknown_option_is_uncertified() -> None:
    certificate = classify_grouped_producer_step(_contract_step(fill_value="", extra_unreviewed=1))
    assert certificate == Uncertified(reason="unknown_option", detail="contract_grouped_xref")


def test_mutable_fill_value_is_uncertified_but_direct_runtime_remains_supported() -> None:
    fill = _MutableFill("before")
    step = _contract_step(column_keys=["k1", "k2"], fill_value=fill)

    # Authentic maintained binding, including the exact by-reference leaf
    # that previously received a GroupedProducerCertificate.
    assert type(step.fn) is BoundFramesTargetCall
    assert step.fn.kwargs["fill_value"] is fill
    assert classify_grouped_producer_step(step) == Uncertified(
        reason="unsupported_configuration_value", detail="fill_value"
    )

    # Certification fails closed, while the trusted direct/programmatic API's
    # existing Any-valued fill behavior remains unchanged.
    fill.marker = "after"
    frames = {
        "source": pd.DataFrame(
            [{"variable_id": "v1", "column_key": "k1", "value": "present"}]
        ),
        "variables": pd.DataFrame(
            {"variable_id": ["k1", "k2"], "group": ["G1", "G2"]}
        ),
        "_meta": {},
    }
    result = step(frames)
    missing_cell = result["grouped"].frame["k2"].iloc[0]
    assert missing_cell is fill
    assert missing_cell.marker == "after"


@pytest.mark.parametrize("fill_value", ["", None, False, 0, 1.5])
def test_closed_scalar_fill_values_remain_certifiable(fill_value: object) -> None:
    certificate = classify_grouped_producer_step(_contract_step(fill_value=fill_value))
    assert isinstance(certificate, GroupedProducerCertificate)


def test_omitted_default_fill_value_remains_certifiable() -> None:
    certificate = classify_grouped_producer_step(_contract_step())
    assert isinstance(certificate, GroupedProducerCertificate)


def test_mutable_iterable_grouped_option_is_also_uncertified() -> None:
    label_columns = _MutableNames("group_a")
    step = _contract_step(label_columns=label_columns)

    assert step.fn.kwargs["label_columns"] is label_columns
    assert classify_grouped_producer_step(step) == Uncertified(
        reason="unsupported_configuration_value", detail="label_columns"
    )

    # This sibling is role-relevant too: mutation changes the visible grouped
    # header selected by the direct family call, without changing that API.
    label_columns.names[:] = ["group_b"]
    frames = {
        "source": pd.DataFrame(
            [{"variable_id": "v1", "column_key": "k1", "value": "present"}]
        ),
        "variables": pd.DataFrame(
            {"variable_id": ["k1"], "group_a": ["A"], "group_b": ["B"]}
        ),
        "_meta": {},
    }
    result = step(frames)
    assert result["grouped"].header.columns[1].labels == ("B",)


def test_reconstruct_mutable_iterable_option_is_uncertified() -> None:
    label_columns = _MutableNames("group")
    certificate = classify_grouped_producer_step(
        _reconstruct_step(label_columns=label_columns)
    )
    assert certificate == Uncertified(
        reason="unsupported_configuration_value", detail="label_columns"
    )


def test_expand_mutable_iterable_is_uncertified_but_direct_runtime_remains_supported() -> None:
    label_columns = _MutableNames("group_a")
    step = _expand_step(label_columns=label_columns)

    # The maintained binding retains this opaque leaf by reference, so the
    # controlled-role classifier must reject it before granting authority.
    assert type(step.fn) is BoundFramesTargetCall
    assert step.fn.kwargs["label_columns"] is label_columns
    assert classify_expand_grouped_step(step) == Uncertified(
        reason="unsupported_configuration_value", detail="label_columns"
    )

    # Caller mutation cannot coexist with certification, while the trusted
    # direct/programmatic family API continues to accept the custom iterable.
    label_columns.names[:] = ["group_b"]
    assert classify_expand_grouped_step(step) == Uncertified(
        reason="unsupported_configuration_value", detail="label_columns"
    )
    frames = {
        "source": pd.DataFrame(
            [{"variable_id": "v1", "column_key": "k1", "value": "present"}]
        ),
        "variables": pd.DataFrame(
            {"variable_id": ["k1"], "group_a": ["A"], "group_b": ["B"]}
        ),
        "_meta": {},
    }
    grouped_frames = contract_grouped_xref(
        frames,
        relation="source",
        output="grouped",
        row_keys="variable_id",
        source_frame="variables",
        key_column="variable_id",
        label_columns=["group_b"],
        column_key="column_key",
        value="value",
    )
    assert step(grouped_frames)["expanded"].to_dict("records") == [
        {"variable_id": "v1", "column_key": "k1", "value": "present"}
    ]


def test_expand_closed_scalar_and_string_sequence_options_remain_certifiable() -> None:
    certificate = classify_expand_grouped_step(
        _expand_step(
            row_keys=("variable_id",),
            label_columns=["group"],
            value_columns=["k1"],
            base_relation="base",
            order_policy="columns",
            order_columns=("sort_order",),
            drop_source=True,
            xref_config_id="grouped-roundtrip",
        )
    )
    assert certificate == ExpandGroupedCertificate(
        matrix="grouped",
        output="expanded",
        output_value_column="value",
        source_frame="variables",
        base_relation="base",
        drop_source=True,
    )


def test_dense_axes_is_unrepresentable_and_stays_uncertified() -> None:
    # dense_axes.rows_from/columns_from may itself name a further frame
    # (dense_axes.py: _axis_source_config reads frames[config["frame"]]),
    # which this classifier cannot safely declare a footprint for without
    # re-implementing that family-owned parsing (F3 audit).
    certificate = classify_grouped_producer_step(
        _contract_step(dense_axes={"rows_from": {"frame": "row_labels", "key": "key"}})
    )
    assert certificate == Uncertified(reason="uncovered_configuration", detail="dense_axes")


def test_two_disjoint_grouped_introductions_both_remain_authorized() -> None:
    existing = grouped_matrix_role(classify_grouped_producer_step(_contract_step(output="grouped_a")))
    new_certificate = classify_grouped_producer_step(
        _contract_step(relation="other_source", output="grouped_b", source_frame="other_variables")
    )
    assert isinstance(new_certificate, GroupedProducerCertificate)

    result = disjoint_grouped_introduction(existing, new_certificate)
    assert result is existing


def test_footprint_collision_deliberately_rejects() -> None:
    existing = grouped_matrix_role(classify_grouped_producer_step(_contract_step(output="grouped_a")))
    # The second transition reads the *first*'s output frame as its own
    # relation -- its footprint intersects the existing role's location.
    colliding_certificate = classify_grouped_producer_step(
        _contract_step(relation="grouped_a", output="grouped_b")
    )
    assert isinstance(colliding_certificate, GroupedProducerCertificate)

    result = disjoint_grouped_introduction(existing, colliding_certificate)
    assert result == Uncertified(reason="locality_collision", detail="grouped_a")


def test_source_frame_collision_deliberately_rejects() -> None:
    """F3 falsification (independent E4 implementation review section 6,
    reproduced exactly): a second transition whose *label-source* frame
    (`source_frame`), not its relation/output, collides with an existing
    role's frame must also be rejected -- the footprint must not be silent
    about this real, classifier-accepted, genuinely-read dependency."""
    existing = grouped_matrix_role(classify_grouped_producer_step(_contract_step(output="A")))
    # relation/output are disjoint from "A", but source_frame="A" -- the
    # axis-mapping label source -- is not.
    second_certificate = classify_grouped_producer_step(
        _contract_step(relation="B_rel", output="B_out", source_frame="A")
    )
    assert isinstance(second_certificate, GroupedProducerCertificate)
    assert "A" in second_certificate.footprint().reads

    result = disjoint_grouped_introduction(existing, second_certificate)
    assert result == Uncertified(reason="locality_collision", detail="A")


def test_source_frame_is_a_real_load_bearing_read_dependency() -> None:
    """Independently confirms the review's runtime claim: `source_frame` is
    genuinely read and validated by `contract_grouped_xref`, not merely an
    accepted-but-inert option -- proving the footprint fix above reflects
    real behavior, not a hypothetical concern."""
    relation = pd.DataFrame(
        {"variable_id": ["v1", "v2"], "column_key": ["k1", "k1"], "value": ["a", "b"]}
    )
    # "labels" is missing the row for key "k1" entirely, so resolving the
    # axis mapping against it must fail -- proving frame A's *content* is
    # actually read and validated during this transition.
    labels = pd.DataFrame({"key": ["other_key"], "group": ["Group"]})
    frames = {"relation": relation, "labels": labels}

    with pytest.raises(AxisMappingError):
        contract_grouped_xref(
            frames,
            relation="relation",
            output="grouped",
            row_keys="variable_id",
            source_frame="labels",
            key_column="key",
            label_columns=["group"],
        )


def test_drop_source_footprint_also_collides_with_a_role_at_the_dropped_frame() -> None:
    existing = grouped_matrix_role(classify_grouped_producer_step(_reconstruct_step(output="grouped_a")))
    # A later transition that *drops* the frame currently holding `existing`
    # collides even though it never "writes" that frame's contents.
    dropping_certificate = classify_grouped_producer_step(
        _contract_step(relation="grouped_a", output="grouped_b", drop_source=True)
    )
    assert isinstance(dropping_certificate, GroupedProducerCertificate)

    result = disjoint_grouped_introduction(existing, dropping_certificate)
    assert result == Uncertified(reason="locality_collision", detail="grouped_a")
