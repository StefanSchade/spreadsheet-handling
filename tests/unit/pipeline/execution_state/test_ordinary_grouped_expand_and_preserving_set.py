"""Ordinary GroupedMatrix expand endpoint and the preserving-certificate set.

Covers the ordinary (all-Scalar) half of maintained flow #5 (ExactTable ->
reconstruct_grouped_matrix -> expand_grouped_xref, both drop modes) and
proves the preserving-certificate representation exists while its initial
set may remain zero (FTR section 22, final bullet).
"""
from __future__ import annotations

import pytest

from spreadsheet_handling.pipeline.build import build_steps_from_config
from spreadsheet_handling.pipeline.execution_state import (
    PRESERVING_CERTIFICATES,
    GroupedMatrixRole,
    PreservingCertificate,
    Uncertified,
    classify_expand_grouped_step,
    classify_grouped_producer_step,
    grouped_matrix_role,
    resolve_grouped_matrix_expand_transition,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _role() -> GroupedMatrixRole:
    certificate = classify_grouped_producer_step(
        build_steps_from_config(
            [
                {
                    "step": "reconstruct_grouped_matrix",
                    "table": "parsed",
                    "output": "grouped",
                    "row_keys": "variable_id",
                    "source_frame": "labels",
                    "key_column": "key",
                    "label_columns": ["grp"],
                }
            ]
        )[0]
    )
    return grouped_matrix_role(certificate)


def _expand_certificate(drop_source: bool):
    step = build_steps_from_config(
        [
            {
                "step": "expand_grouped_xref",
                "matrix": "grouped",
                "output": "expanded",
                "row_keys": "variable_id",
                "source_frame": "labels",
                "key_column": "key",
                "label_columns": ["grp"],
                "drop_source": drop_source,
            }
        ]
    )[0]
    return classify_expand_grouped_step(step)


def test_retain_mode_keeps_the_role_unchanged() -> None:
    role = _role()
    result = resolve_grouped_matrix_expand_transition(_expand_certificate(False), role)
    assert result == role


def test_drop_mode_terminates_the_role_with_no_replacement() -> None:
    role = _role()
    result = resolve_grouped_matrix_expand_transition(_expand_certificate(True), role)
    assert result is None


def test_mismatched_matrix_frame_is_uncertified() -> None:
    role = _role()
    certificate = _expand_certificate(False)
    other_frame_certificate = type(certificate)(
        matrix="different_frame",
        output=certificate.output,
        output_value_column=certificate.output_value_column,
        source_frame=certificate.source_frame,
        base_relation=certificate.base_relation,
        drop_source=certificate.drop_source,
    )
    result = resolve_grouped_matrix_expand_transition(other_frame_certificate, role)
    assert result == Uncertified(reason="mismatched_composition", detail="matrix")


def test_expand_footprint_includes_source_frame_and_base_relation_when_present() -> None:
    """F3 audit (independent E4 implementation review section 6): both the
    axis-mapping label-source frame and, when supplied, the scoped-
    recomposition `base_relation` are genuine read dependencies of
    `expand_grouped_xref` (`xref_crosstable/operation.py`:
    `_require_frame(frames, base_relation)`) and must appear in the
    declared footprint."""
    step = build_steps_from_config(
        [
            {
                "step": "expand_grouped_xref",
                "matrix": "grouped",
                "output": "expanded",
                "row_keys": "variable_id",
                "source_frame": "labels",
                "key_column": "key",
                "label_columns": ["grp"],
                "base_relation": "base",
            }
        ]
    )[0]
    certificate = classify_expand_grouped_step(step)
    assert certificate.source_frame == "labels"
    assert certificate.base_relation == "base"
    reads = certificate.footprint().reads
    assert {"grouped", "labels", "base"} <= reads


def test_preserving_certificate_set_may_remain_zero() -> None:
    # The representation exists...
    assert PreservingCertificate(target="x:y", closed_options=("a",), evidence="test")
    # ...but the accepted architecture proves all twelve maintained flows
    # close without needing one (Review 005, "Twelve-flow zero-preserving
    # proof"), so the initial evidence-backed set is empty.
    assert PRESERVING_CERTIFICATES == ()
