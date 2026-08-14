"""Phase-E slice E4: exact producer-transition representation and bounded certificates.

Authority: ``docs/backlog/FTR-TRUSTED-INGRESS-P4A.adoc`` section 23 ("E4 --
exact producer-transition representation and bounded certificates"), under
the architecture accepted by Independent Follow-up Review 005
(``docs/backlog/FTR-TRUSTED-INGRESS-P4A_review.adoc``).

This package gives E5 (framework-managed macro wiring, not implemented here)
a truthful, implementation-local answer to: *what exact transition does this
bound invocation authorize, what execution state does it require, what roles
does it introduce/retain/derive/relocate/consume, what footprint proves
another role's preservation, or is this invocation simply UNCERTIFIED?*
Nothing here runs ingress, threads state through the orchestrator, or
enforces anything at pipeline execution time -- see the FTR's "Do not
prematurely implement E5" boundary (section 20).

Layering: this package lives under ``pipeline/`` rather than
``domain/ingress/`` because it must inspect ``pipeline.types.BoundStep``
(the "current binding representation" section 3 asks E4 to inspect) *and*
compare against domain/core role types (``LookupFormulaSpec``,
``GroupedMatrix``). The architecture layer map
(``docs/ai_info/architecture_primer.adoc``) places Pipeline above Domain and
Core, so only the pipeline layer may depend on both without inverting the
allowed dependency direction.

Execution-state algebra (FTR section 7)
----------------------------------------

::

    ConformantFrameworkExecutionState
      ::= OrdinaryFactsOutsideControlledRoles + ControlledRole*

    ControlledRole
      ::= LookupFormulaSpec@declared-helper-cell-role
        | GroupedMatrix@producer-declared-frame-role
        | ArtifactManifestSourceFrames@producer-declared-output-frame.source_frames

    ControlledRoleComposition
      ::= DisjointRoleProduct@exact-locality-proof
        | GroupedMatrix[LookupFormulaSpec@grouped-dynamic-value-cell-role]
            @exact-formula-grouped-composition

Module map
----------

``vocabulary``
    ``TransitionEffect`` (INTRODUCE / COPY_DERIVE / RELOCATE /
    CONSUME_TERMINATE / PENDING_CLEANUP), the closed ``Uncertified`` outcome,
    and ``TransitionFootprint`` / ``proves_disjoint`` for the bounded
    disjoint-role-product proof.
``roles``
    The four closed role descriptors (``LookupFormulaSpecRole``,
    ``GroupedMatrixRole``, ``GroupedMatrixFormulaRole``,
    ``ArtifactManifestSourceFramesRole``) and
    ``terminate_roles_removed_by_cleanup``.
``bound_configuration``
    The shared exact-bound-configuration snapshot primitives (mutation-safety
    strategy for FTR section 18).
``preserving``
    ``PreservingCertificate`` and the (deliberately empty)
    ``PRESERVING_CERTIFICATES`` initial set (FTR section 5).
``formula_helper``
    Standalone ``LookupFormulaSpec`` introduction via
    ``add_lookup_helpers(helper_value_mode="formula")``.
``grouped_matrix``
    Standalone ``GroupedMatrix`` introduction (``contract_grouped_xref`` /
    ``reconstruct_grouped_matrix``), the FormulaSpec-in-GroupedMatrix nested
    composition, disjoint-locality proof for repeated introduction, and the
    reverse ``expand_grouped_xref`` retain/drop endpoints.
``artifact_manifest``
    The manifest ``source_frames`` role (M1).
``projection``
    The workbook projection/sink exit representation (FTR section 14):
    outer-role termination, nested-FormulaSpec relocation to the render
    cell, and the referenced-lookup-sheet-rename rejection (compatibility
    rule B).

Closed default: every classifier in this package returns ``Uncertified``
unless a bound invocation matches one of the exact reviewed configurations
above -- known callable identity, registry membership, family, wrapper, or
matching output shape never substitute for that exact match (FTR section 4).
"""
from __future__ import annotations

from .artifact_manifest import (
    WRITE_ARTIFACT_MANIFEST_TARGET,
    ArtifactManifestCertificate,
    artifact_manifest_role,
    classify_artifact_manifest_step,
)
from .bound_configuration import only_known_keys, snapshot_scalar, snapshot_string_sequence
from .formula_helper import (
    FORMULA_HELPER_TARGET,
    FormulaHelperCertificate,
    classify_formula_helper_step,
    formula_helper_roles,
)
from .grouped_matrix import (
    CONTRACT_GROUPED_XREF_TARGET,
    EXPAND_GROUPED_XREF_TARGET,
    RECONSTRUCT_GROUPED_MATRIX_TARGET,
    ExpandDropProduct,
    ExpandGroupedCertificate,
    ExpandRetainProduct,
    FormulaGroupedComposition,
    GroupedProducerCertificate,
    classify_expand_grouped_step,
    classify_grouped_producer_step,
    compose_formula_to_grouped,
    disjoint_grouped_introduction,
    dynamic_column_labels,
    grouped_matrix_role,
    resolve_formula_expand_transition,
    resolve_grouped_matrix_expand_transition,
)
from .preserving import PRESERVING_CERTIFICATES, PreservingCertificate
from .projection import (
    reject_referenced_lookup_sheet_rename,
    relocate_nested_formula_at_projection,
    terminate_grouped_matrix_at_projection,
)
from .roles import (
    ArtifactManifestSourceFramesRole,
    ControlledRole,
    GroupedMatrixFormulaRole,
    GroupedMatrixRole,
    LookupFormulaSpecRole,
    terminate_roles_removed_by_cleanup,
)
from .vocabulary import TransitionEffect, TransitionFootprint, Uncertified, proves_disjoint

__all__ = [
    # vocabulary
    "TransitionEffect",
    "Uncertified",
    "TransitionFootprint",
    "proves_disjoint",
    # roles
    "LookupFormulaSpecRole",
    "GroupedMatrixRole",
    "GroupedMatrixFormulaRole",
    "ArtifactManifestSourceFramesRole",
    "ControlledRole",
    "terminate_roles_removed_by_cleanup",
    # bound configuration
    "snapshot_scalar",
    "snapshot_string_sequence",
    "only_known_keys",
    # preserving
    "PreservingCertificate",
    "PRESERVING_CERTIFICATES",
    # formula helper
    "FORMULA_HELPER_TARGET",
    "FormulaHelperCertificate",
    "classify_formula_helper_step",
    "formula_helper_roles",
    # grouped matrix
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
    # artifact manifest
    "WRITE_ARTIFACT_MANIFEST_TARGET",
    "ArtifactManifestCertificate",
    "classify_artifact_manifest_step",
    "artifact_manifest_role",
    # projection / sink
    "terminate_grouped_matrix_at_projection",
    "relocate_nested_formula_at_projection",
    "reject_referenced_lookup_sheet_rename",
]
