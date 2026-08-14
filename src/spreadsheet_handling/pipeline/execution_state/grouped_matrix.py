"""GroupedMatrix producer/consumer transitions (FTR sections 9-13).

Covers, in the FTR's own vocabulary:

* standalone ``GroupedMatrix`` introduction by ``contract_grouped_xref`` or
  ``reconstruct_grouped_matrix`` (section 10, "GroupedMatrix lifecycle
  decision");
* the one admitted nested composition,
  ``GroupedMatrix[LookupFormulaSpec@grouped-dynamic-value-cell-role]``
  (section 10, "FormulaSpec-in-GroupedMatrix composition descriptor");
* the bounded disjoint-role-product/locality rule for a second, independent
  ``GroupedMatrix`` introduction (section 10, "Controlled-role composition
  decision");
* the reverse ``expand_grouped_xref`` endpoints, both ``drop_source`` modes,
  for the nested-formula case (section 10, "FormulaSpec-in-GroupedMatrix
  composition descriptor" and section 13).

Geometry, header pairing, bijection, and reconstruction semantics remain
entirely family-owned (``domain/transformations/grouped_xref/``); this module
never re-implements them. It only reads the already-validated
``GroupedHeader``/``DynamicColumn`` value objects to resolve which physical
columns a role occupies -- the same safe, closed dispatch
``grouped_matrix_to_exact_table`` already performs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from spreadsheet_handling.domain.transformations.grouped_xref import GroupedMatrix
from spreadsheet_handling.domain.transformations.grouped_xref.model import DynamicColumn
from spreadsheet_handling.pipeline.types import BoundStep

from .bound_configuration import only_known_keys, snapshot_scalar, snapshot_string_sequence
from .formula_helper import FormulaHelperCertificate
from .roles import GroupedMatrixFormulaRole, GroupedMatrixRole, LookupFormulaSpecRole
from .vocabulary import TransitionEffect, TransitionFootprint, Uncertified, proves_disjoint

CONTRACT_GROUPED_XREF_TARGET = (
    "spreadsheet_handling.domain.transformations.grouped_xref:contract_grouped_xref"
)
RECONSTRUCT_GROUPED_MATRIX_TARGET = (
    "spreadsheet_handling.domain.transformations.grouped_xref:reconstruct_grouped_matrix"
)
EXPAND_GROUPED_XREF_TARGET = (
    "spreadsheet_handling.domain.transformations.grouped_xref:expand_grouped_xref"
)

_ProducerKind = Literal["contract_grouped_xref", "reconstruct_grouped_matrix"]

_CONTRACT_KNOWN_KEYS = frozenset(
    {
        "target",
        "relation",
        "output",
        "row_keys",
        "source_frame",
        "key_column",
        "label_columns",
        "column_key",
        "value",
        "column_keys",
        "dense_axes",
        "fill_value",
        "level_names",
        "order_policy",
        "order_columns",
        "drop_source",
        "xref_config_id",
    }
)
_RECONSTRUCT_KNOWN_KEYS = frozenset(
    {
        "target",
        "table",
        "output",
        "row_keys",
        "source_frame",
        "key_column",
        "label_columns",
        "level_names",
        "order_policy",
        "order_columns",
        "drop_source",
    }
)
_EXPAND_KNOWN_KEYS = frozenset(
    {
        "target",
        "matrix",
        "output",
        "row_keys",
        "source_frame",
        "key_column",
        "label_columns",
        "column_key",
        "value",
        "value_columns",
        "base_relation",
        "order_policy",
        "order_columns",
        "drop_source",
        "xref_config_id",
    }
)


# ---------------------------------------------------------------------------
# Standalone producer introduction (contract_grouped_xref / reconstruct_grouped_matrix)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupedProducerCertificate:
    """The exact reviewed grouped-producer configuration.

    ``value_column`` is the selected value column for ``contract_grouped_xref``
    (``None`` for ``reconstruct_grouped_matrix``, which has no such
    parameter); it is what the composition classifier below matches against
    a retained ``FormulaHelperCertificate.fields`` entry.
    """

    producer: _ProducerKind
    output: str
    source: str
    value_column: str | None
    drop_source: bool
    row_keys: tuple[str, ...]

    def footprint(self) -> TransitionFootprint:
        drops = frozenset({self.source}) if self.drop_source else frozenset()
        return TransitionFootprint(
            reads=frozenset({self.source}), writes=frozenset({self.output}), drops=drops
        )


def classify_grouped_producer_step(step: BoundStep) -> GroupedProducerCertificate | Uncertified:
    """Classify one bound ``contract_grouped_xref`` or ``reconstruct_grouped_matrix`` call."""
    config = step.config
    target = config.get("target")
    if target == CONTRACT_GROUPED_XREF_TARGET:
        return _classify_contract(config)
    if target == RECONSTRUCT_GROUPED_MATRIX_TARGET:
        return _classify_reconstruct(config)
    return Uncertified(reason="unrecognized_target")


def _classify_contract(config: dict) -> GroupedProducerCertificate | Uncertified:
    if not only_known_keys(config, known=_CONTRACT_KNOWN_KEYS):
        return Uncertified(reason="unknown_option", detail="contract_grouped_xref")
    relation = snapshot_scalar(config.get("relation"))
    output = snapshot_scalar(config.get("output"))
    value = snapshot_scalar(config.get("value", "value"))
    drop_source = snapshot_scalar(config.get("drop_source", False))
    row_keys = snapshot_string_sequence(config.get("row_keys"))
    if not (_is_nonempty_str(relation) and _is_nonempty_str(output) and _is_nonempty_str(value)):
        return Uncertified(
            reason="unsupported_configuration_value", detail="relation/output/value"
        )
    if type(drop_source) is not bool:
        return Uncertified(reason="unsupported_configuration_value", detail="drop_source")
    if row_keys is None:
        return Uncertified(reason="unsupported_configuration_value", detail="row_keys")
    return GroupedProducerCertificate(
        producer="contract_grouped_xref",
        output=output,
        source=relation,
        value_column=value,
        drop_source=drop_source,
        row_keys=row_keys,
    )


def _classify_reconstruct(config: dict) -> GroupedProducerCertificate | Uncertified:
    if not only_known_keys(config, known=_RECONSTRUCT_KNOWN_KEYS):
        return Uncertified(reason="unknown_option", detail="reconstruct_grouped_matrix")
    table = snapshot_scalar(config.get("table"))
    output = snapshot_scalar(config.get("output"))
    drop_source = snapshot_scalar(config.get("drop_source", False))
    row_keys = snapshot_string_sequence(config.get("row_keys"))
    if not (_is_nonempty_str(table) and _is_nonempty_str(output)):
        return Uncertified(reason="unsupported_configuration_value", detail="table/output")
    if type(drop_source) is not bool:
        return Uncertified(reason="unsupported_configuration_value", detail="drop_source")
    if row_keys is None:
        return Uncertified(reason="unsupported_configuration_value", detail="row_keys")
    return GroupedProducerCertificate(
        producer="reconstruct_grouped_matrix",
        output=output,
        source=table,
        value_column=None,
        drop_source=drop_source,
        row_keys=row_keys,
    )


def _is_nonempty_str(value: object) -> bool:
    return type(value) is str and value != ""


def grouped_matrix_role(certificate: GroupedProducerCertificate) -> GroupedMatrixRole:
    return GroupedMatrixRole(
        frame=certificate.output,
        producer=certificate.producer,
        source=certificate.source,
        effect=TransitionEffect.INTRODUCE,
    )


# ---------------------------------------------------------------------------
# Disjoint-role-product / locality (repeated grouped introduction)
# ---------------------------------------------------------------------------


def disjoint_grouped_introduction(
    existing: GroupedMatrixRole,
    new_certificate: GroupedProducerCertificate,
) -> GroupedMatrixRole | Uncertified:
    """FTR section 10, "Controlled-role composition decision": the repeated
    grouped introduction is the minimum evidenced disjoint-product case.

    A second exact grouped introduction preserves an already-live
    ``GroupedMatrixRole`` only when its footprint provably does not intersect
    that role's frame.
    """
    if not proves_disjoint(new_certificate.footprint(), existing_role_frame=existing.frame):
        return Uncertified(reason="locality_collision", detail=existing.frame)
    return existing


# ---------------------------------------------------------------------------
# FormulaSpec-in-GroupedMatrix composition (forward)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FormulaGroupedComposition:
    """The exact product FTR section 11 requires:

    ``FormulaSpec@retained-source-helper-location(s) *
    GroupedMatrix[FormulaSpec@grouped-dynamic-value-cell-role]``
    """

    retained_source: tuple[LookupFormulaSpecRole, ...]
    nested: GroupedMatrixFormulaRole


def compose_formula_to_grouped(
    formula: FormulaHelperCertificate,
    grouped: GroupedProducerCertificate,
) -> FormulaGroupedComposition | Uncertified:
    """The one admitted nested composition (FTR sections 10-11).

    ``grouped`` must be an exact ``contract_grouped_xref`` invocation whose
    ``relation`` is exactly ``formula``'s declared output frame, whose
    selected ``value`` column is exactly one of ``formula``'s introduced
    fields, and whose ``row_keys`` retain ``formula``'s source-key column so
    its same-row reference stays defined. Every source helper role remains
    live; only the selected helper additionally derives into the nested
    grouped locations (unselected helpers keep their standalone role only).
    """
    if grouped.producer != "contract_grouped_xref":
        return Uncertified(reason="mismatched_composition", detail="producer")
    if grouped.source != formula.output:
        return Uncertified(reason="mismatched_composition", detail="source_frame")
    if grouped.value_column not in formula.fields:
        return Uncertified(reason="mismatched_composition", detail="value_column")
    if formula.source_key_column not in grouped.row_keys:
        return Uncertified(reason="mismatched_composition", detail="row_keys")
    if grouped.output == formula.output:
        return Uncertified(reason="mismatched_composition", detail="output_collision")

    pending = grouped.drop_source
    retained_source = tuple(
        LookupFormulaSpecRole(
            frame=formula.output,
            column=field,
            source_key_column=formula.source_key_column,
            lookup_sheet=formula.lookup,
            lookup_key_column=formula.lookup_key_column,
            missing=formula.missing,
            effect=TransitionEffect.PENDING_CLEANUP if pending else TransitionEffect.INTRODUCE,
            pending_cleanup=pending,
        )
        for field in formula.fields
    )
    selected_source = next(
        role for role in retained_source if role.column == grouped.value_column
    )
    nested = GroupedMatrixFormulaRole(
        frame=grouped.output,
        source=selected_source,
        effect=TransitionEffect.COPY_DERIVE,
    )
    return FormulaGroupedComposition(retained_source=retained_source, nested=nested)


# ---------------------------------------------------------------------------
# Reverse: expand_grouped_xref
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpandGroupedCertificate:
    """The exact reviewed ``expand_grouped_xref`` configuration."""

    matrix: str
    output: str
    output_value_column: str
    drop_source: bool

    def footprint(self) -> TransitionFootprint:
        # ``drop_source=True`` does not remove ``matrix`` from the returned
        # Frames mapping -- it publishes the restored flat frame there and
        # marks it pending cleanup (Review 005 section 6), mirroring
        # contract_grouped_xref's own drop_source bookkeeping. ``drops``
        # therefore names "marked for later cleanup", not "removed now".
        drops = frozenset({self.matrix}) if self.drop_source else frozenset()
        return TransitionFootprint(
            reads=frozenset({self.matrix}),
            writes=frozenset({self.output, self.matrix}),
            drops=drops,
        )


def classify_expand_grouped_step(step: BoundStep) -> ExpandGroupedCertificate | Uncertified:
    config = step.config
    if config.get("target") != EXPAND_GROUPED_XREF_TARGET:
        return Uncertified(reason="unrecognized_target")
    if not only_known_keys(config, known=_EXPAND_KNOWN_KEYS):
        return Uncertified(reason="unknown_option", detail="expand_grouped_xref")
    matrix = snapshot_scalar(config.get("matrix"))
    output = snapshot_scalar(config.get("output"))
    value = snapshot_scalar(config.get("value", "value"))
    drop_source = snapshot_scalar(config.get("drop_source", False))
    if not (_is_nonempty_str(matrix) and _is_nonempty_str(output) and _is_nonempty_str(value)):
        return Uncertified(
            reason="unsupported_configuration_value", detail="matrix/output/value"
        )
    if type(drop_source) is not bool:
        return Uncertified(reason="unsupported_configuration_value", detail="drop_source")
    return ExpandGroupedCertificate(
        matrix=matrix, output=output, output_value_column=value, drop_source=drop_source
    )


def resolve_grouped_matrix_expand_transition(
    certificate: ExpandGroupedCertificate,
    role: GroupedMatrixRole,
) -> GroupedMatrixRole | None | Uncertified:
    """Ordinary (all-Scalar) ``GroupedMatrix`` expansion (FTR section 13.A/13.B,
    ordinary case; maintained flow #5).

    Returns the role unchanged when retained (``drop_source=False``), or
    ``None`` when the carrier's identity terminates inside expansion
    (``drop_source=True``) -- there is no ``GroupedMatrixRole`` left to
    report; the caller's own frame-removal handling covers the ordinary flat
    source it leaves behind.
    """
    if role.frame != certificate.matrix:
        return Uncertified(reason="mismatched_composition", detail="matrix")
    if certificate.drop_source:
        return None
    return role


@dataclass(frozen=True)
class ExpandRetainProduct:
    """``drop_source=False``: nested source retained * standalone output derived.

    FTR section 10: ``GroupedMatrix[FormulaSpec]@retained-source *
    FormulaSpec@expanded-output-value-column``.
    """

    nested: GroupedMatrixFormulaRole
    output: LookupFormulaSpecRole


@dataclass(frozen=True)
class ExpandDropProduct:
    """``drop_source=True``: outer identity terminates; restored flat source
    pending cleanup * standalone output derived.

    FTR section 10: ``FormulaSpec@restored-flat-source-value-locations[pending-cleanup]
    * FormulaSpec@expanded-output-value-column``.
    """

    restored_source: tuple[LookupFormulaSpecRole, ...]
    output: LookupFormulaSpecRole
    terminated: GroupedMatrixFormulaRole


def dynamic_column_labels(matrix: GroupedMatrix) -> tuple[str, ...]:
    """The physical flat-matrix column labels of every dynamic (non-row-key)
    column described by ``matrix.header``, in header order.

    Reads ``matrix.frame.columns`` positionally against
    ``matrix.header.columns`` -- the same closed
    ``RowKeyColumn``/``DynamicColumn`` dispatch already performed by
    ``grouped_matrix_to_exact_table`` -- rather than re-deriving canonical
    keys, which stay family-owned.
    """
    columns = matrix.frame.columns
    return tuple(
        str(columns[column.position])
        for column in matrix.header.columns
        if type(column) is DynamicColumn
    )


def resolve_formula_expand_transition(
    certificate: ExpandGroupedCertificate,
    nested: GroupedMatrixFormulaRole,
    *,
    restored_dynamic_columns: tuple[str, ...],
) -> ExpandRetainProduct | ExpandDropProduct | Uncertified:
    """Compute the exact post-transition role state for expanding a
    ``GroupedMatrix[LookupFormulaSpec]`` (FTR section 10, reverse endpoints).

    ``restored_dynamic_columns`` names the exact dynamic column labels of the
    flat matrix restored inside expansion for the ``drop_source=True`` case
    (resolve via ``dynamic_column_labels`` against the live matrix before it
    is expanded); it is not knowable from bound configuration alone and is
    ignored when ``drop_source=False``.
    """
    if nested.frame != certificate.matrix:
        return Uncertified(reason="mismatched_composition", detail="matrix")

    source = nested.source
    output_role = LookupFormulaSpecRole(
        frame=certificate.output,
        column=certificate.output_value_column,
        source_key_column=source.source_key_column,
        lookup_sheet=source.lookup_sheet,
        lookup_key_column=source.lookup_key_column,
        missing=source.missing,
        effect=TransitionEffect.COPY_DERIVE,
    )

    if not certificate.drop_source:
        return ExpandRetainProduct(nested=nested, output=output_role)

    if not restored_dynamic_columns:
        return Uncertified(reason="uncovered_configuration", detail="restored_dynamic_columns")
    restored_source = tuple(
        LookupFormulaSpecRole(
            frame=certificate.matrix,
            column=column,
            source_key_column=source.source_key_column,
            lookup_sheet=source.lookup_sheet,
            lookup_key_column=source.lookup_key_column,
            missing=source.missing,
            effect=TransitionEffect.RELOCATE,
            pending_cleanup=True,
        )
        for column in restored_dynamic_columns
    )
    terminated = GroupedMatrixFormulaRole(
        frame=nested.frame, source=nested.source, effect=TransitionEffect.CONSUME_TERMINATE
    )
    return ExpandDropProduct(restored_source=restored_source, output=output_role, terminated=terminated)


__all__ = [
    "CONTRACT_GROUPED_XREF_TARGET",
    "RECONSTRUCT_GROUPED_MATRIX_TARGET",
    "EXPAND_GROUPED_XREF_TARGET",
    "GroupedProducerCertificate",
    "classify_grouped_producer_step",
    "grouped_matrix_role",
    "disjoint_grouped_introduction",
    "FormulaGroupedComposition",
    "compose_formula_to_grouped",
    "ExpandGroupedCertificate",
    "classify_expand_grouped_step",
    "resolve_grouped_matrix_expand_transition",
    "ExpandRetainProduct",
    "ExpandDropProduct",
    "dynamic_column_labels",
    "resolve_formula_expand_transition",
]
