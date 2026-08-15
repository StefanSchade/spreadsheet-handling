"""Phase-E slice E5: framework-managed macro execution state.

Authority: ``docs/backlog/FTR-TRUSTED-INGRESS-P4A.adoc`` section 23 ("E5 --
framework-managed macro wiring"), under the architecture accepted by
Independent Follow-up Review 005 and the E4 representation accepted for
``pipeline.execution_state``.

This module is the one small, named macro execution component E5 wires into
:func:`spreadsheet_handling.application.orchestrator.orchestrate`. It answers,
for the *single* framework-owned macro seam (``orchestrate``, which every
router-backed entry point -- ``sheets-run``, ``run_app``, the compatibility
shim, ``sheets-schema-maintain``/``run_schema_maintenance`` -- funnels
through, per FTR section 6's entry-surface table):

* :func:`establish_initial_state` -- run E1-E3 ordinary conformance ingress
  (via the existing ``domain.ingress`` coordinator, now including the E2
  ``ordinary_structural_admission`` rule) before any configured step, and
  start with zero controlled roles.
* :func:`execute_managed_step` -- classify one bound step with the exact E4
  classifiers, execute it exactly once, and apply its declared transition (or
  the closed uncertified fallback: ordinary re-establishment, ending all
  prior controlled-role authority) to the returned execution state.
* :func:`finalize_managed_state` -- after final domain cleanup, terminate
  every controlled role whose frame cleanup removed, then authorize every
  role still live against the exact final sink kind, rejecting before the
  saver runs if any role is not authorized for that sink.

Execution state (:class:`ManagedExecutionState`) is control-plane only: a
plain, frozen dataclass threaded explicitly by the caller. It is never
written into Frames, ``_meta``, a DataFrame, or any registry -- matching the
same "keep execution authority separate from payload" requirement E4 already
satisfies for its own descriptors (see ``pipeline.execution_state``'s package
docstring).

This module does not change ``run_pipeline`` (``pipeline.execution``): every
step is still executed through it (one step at a time, so its existing
debug/meta-diff tracing keeps working), and callers of ``run_pipeline``
outside this macro still receive no automatic ingress or re-establishment --
see FTR section 6, the ``run_pipeline`` row ("No" automatic conformance
establishment).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from ..domain.ingress.structural_admission import admit_ordinary_frames
from ..domain.transformations.grouped_xref import GroupedMatrix
from ..pipeline.execution import run_pipeline
from ..pipeline.execution_state import (
    ArtifactManifestSourceFramesRole,
    ControlledRole,
    ExpandDropProduct,
    ExpandRetainProduct,
    FORMULA_CAPABLE_SINK_KINDS,
    FormulaHelperCertificate,
    GroupedMatrixFormulaRole,
    GroupedMatrixRole,
    LookupFormulaSpecRole,
    MANIFEST_ADAPTER_SINK_KIND,
    Uncertified,
    artifact_manifest_role,
    classify_artifact_manifest_step,
    classify_expand_grouped_step,
    classify_formula_helper_step,
    classify_grouped_producer_step,
    compose_formula_to_grouped,
    dynamic_column_labels,
    formula_helper_roles,
    grouped_matrix_role,
    proves_disjoint,
    reject_referenced_lookup_sheet_rename,
    resolve_formula_expand_transition,
    resolve_grouped_matrix_expand_transition,
    terminate_roles_removed_by_cleanup,
)
from ..pipeline.types import BoundStep, Frames

__all__ = [
    "ManagedExecutionState",
    "UnauthorizedControlledRoleAtSinkError",
    "establish_initial_state",
    "execute_managed_step",
    "finalize_managed_state",
]


@dataclass(frozen=True)
class ManagedExecutionState:
    """Control-plane record of every currently-live E4 controlled role.

    ``roles`` is the exact bounded role set (FTR section 7's
    ``ControlledRole*`` algebra). ``last_formula_certificate`` is the smallest
    additional memory the macro needs beyond that set: the one admitted
    nested composition (FormulaSpec-in-GroupedMatrix, FTR section 10) is
    proven from the *originating* ``FormulaHelperCertificate``, not from the
    ``LookupFormulaSpecRole`` values alone, so the macro retains only the
    most recently certified formula-helper certificate -- not a general
    certificate history/registry (explicitly excluded by FTR section 23).
    An uncertified step ends all of it, including this certificate.
    """

    roles: tuple[ControlledRole, ...] = ()
    last_formula_certificate: FormulaHelperCertificate | None = None


class UnauthorizedControlledRoleAtSinkError(RuntimeError):
    """A controlled role survived to the final sink without an exact exit.

    Carries only safe, already-established facts (role kind, its declared
    frame, and the sink kind that failed to authorize it) -- never a
    ``repr()``/``str()`` of the role's payload, matching the classify-before-
    inspect diagnostic discipline the rest of Trusted Ingress uses.
    """

    def __init__(self, *, role_kind: str, frame: str, sink_kind: str) -> None:
        self.role_kind = role_kind
        self.frame = frame
        self.sink_kind = sink_kind
        super().__init__(
            f"controlled role {role_kind!r} at frame {frame!r} is not authorized "
            f"to reach sink kind {sink_kind!r}"
        )


# ---------------------------------------------------------------------------
# Initial establishment
# ---------------------------------------------------------------------------


def establish_initial_state(frames: Frames) -> tuple[Frames, ManagedExecutionState]:
    """E1-E3 ordinary conformance establishment, then zero controlled roles.

    Delegates entirely to the existing, accepted ``domain.ingress`` rule
    coordinator (now including E2's ``ordinary_structural_admission`` rule,
    wired by this slice) -- no walker is duplicated here. A rejection raises
    before this function returns, so the caller never reaches a configured
    step, final cleanup, or a saver with a non-conformant candidate.
    """
    from ..domain import ingress as domain_ingress

    conformant = domain_ingress.run_domain_ingress(frames)
    return conformant, ManagedExecutionState()


# ---------------------------------------------------------------------------
# Per-step classification and transition application
# ---------------------------------------------------------------------------


def _run_one(frames: Frames, step: BoundStep) -> Frames:
    return run_pipeline(frames, (step,))


def _footprint_collides(footprint, roles: tuple[ControlledRole, ...]) -> bool:
    return any(not proves_disjoint(footprint, existing_role_frame=role.frame) for role in roles)


def _role_at_frame(
    roles: tuple[ControlledRole, ...], frame: str
) -> GroupedMatrixRole | GroupedMatrixFormulaRole | None:
    for role in roles:
        if type(role) in (GroupedMatrixRole, GroupedMatrixFormulaRole) and role.frame == frame:
            return role
    return None


def _fallback_uncertified(frames: Frames, step: BoundStep) -> tuple[Frames, ManagedExecutionState]:
    """FTR section 12's closed default: execute, then ordinary re-establish.

    Every prior controlled-role authorization ends unconditionally. Ordinary
    re-establishment naturally rejects any surviving ``GroupedMatrix``,
    ``LookupFormulaSpec``, or manifest ``list[str]`` role -- those are not
    recognized ordinary carriers/Scalar values -- so this single call is
    sufficient to enforce FTR section 12's "anything else" rule without a
    separate role-aware check.
    """
    executed = _run_one(frames, step)
    reestablished = admit_ordinary_frames(executed)
    return reestablished, ManagedExecutionState()


def _handle_formula_helper(
    frames: Frames, state: ManagedExecutionState, step: BoundStep, certificate: FormulaHelperCertificate
) -> tuple[Frames, ManagedExecutionState]:
    if _footprint_collides(certificate.footprint(), state.roles):
        return _fallback_uncertified(frames, step)
    executed = _run_one(frames, step)
    new_state = ManagedExecutionState(
        roles=state.roles + formula_helper_roles(certificate),
        last_formula_certificate=certificate,
    )
    return executed, new_state


def _handle_grouped_producer(frames: Frames, state: ManagedExecutionState, step: BoundStep, certificate):
    composition = None
    if certificate.producer == "contract_grouped_xref" and state.last_formula_certificate is not None:
        candidate = compose_formula_to_grouped(state.last_formula_certificate, certificate)
        if not isinstance(candidate, Uncertified):
            composition = candidate

    if composition is not None:
        formula_output = state.last_formula_certificate.output
        remaining = tuple(
            role
            for role in state.roles
            if not (type(role) is LookupFormulaSpecRole and role.frame == formula_output)
        )
        if _footprint_collides(certificate.footprint(), remaining):
            return _fallback_uncertified(frames, step)
        executed = _run_one(frames, step)
        new_roles = remaining + composition.retained_source + (composition.nested,)
        return executed, ManagedExecutionState(roles=new_roles, last_formula_certificate=None)

    if _footprint_collides(certificate.footprint(), state.roles):
        return _fallback_uncertified(frames, step)
    executed = _run_one(frames, step)
    new_roles = state.roles + (grouped_matrix_role(certificate),)
    return executed, ManagedExecutionState(
        roles=new_roles, last_formula_certificate=state.last_formula_certificate
    )


def _handle_expand_grouped(frames: Frames, state: ManagedExecutionState, step: BoundStep, certificate):
    role_at_matrix = _role_at_frame(state.roles, certificate.matrix)
    if role_at_matrix is None:
        return _fallback_uncertified(frames, step)

    other_roles = tuple(role for role in state.roles if role is not role_at_matrix)
    if _footprint_collides(certificate.footprint(), other_roles):
        return _fallback_uncertified(frames, step)

    if type(role_at_matrix) is GroupedMatrixFormulaRole:
        live_matrix = frames.get(certificate.matrix)
        if type(live_matrix) is not GroupedMatrix:
            return _fallback_uncertified(frames, step)
        restored_columns = (
            dynamic_column_labels(live_matrix) if certificate.drop_source else ()
        )
        result = resolve_formula_expand_transition(
            certificate, role_at_matrix, restored_dynamic_columns=restored_columns
        )
        if isinstance(result, Uncertified):
            return _fallback_uncertified(frames, step)
        executed = _run_one(frames, step)
        if type(result) is ExpandRetainProduct:
            new_roles = other_roles + (result.nested, result.output)
        else:
            assert type(result) is ExpandDropProduct
            new_roles = other_roles + result.restored_source + (result.output,)
        return executed, ManagedExecutionState(
            roles=new_roles, last_formula_certificate=state.last_formula_certificate
        )

    # Ordinary (all-Scalar) GroupedMatrix expansion.
    result = resolve_grouped_matrix_expand_transition(certificate, role_at_matrix)
    if isinstance(result, Uncertified):
        return _fallback_uncertified(frames, step)
    executed = _run_one(frames, step)
    new_roles = other_roles if result is None else other_roles + (result,)
    return executed, ManagedExecutionState(
        roles=new_roles, last_formula_certificate=state.last_formula_certificate
    )


def _handle_artifact_manifest(frames: Frames, state: ManagedExecutionState, step: BoundStep, certificate):
    if _footprint_collides(certificate.footprint(), state.roles):
        return _fallback_uncertified(frames, step)
    executed = _run_one(frames, step)
    new_roles = state.roles + (artifact_manifest_role(certificate),)
    return executed, ManagedExecutionState(
        roles=new_roles, last_formula_certificate=state.last_formula_certificate
    )


def execute_managed_step(
    frames: Frames, state: ManagedExecutionState, step: BoundStep
) -> tuple[Frames, ManagedExecutionState]:
    """Classify ``step`` with the exact E4 classifiers, execute it once, and
    apply its declared transition -- or the closed uncertified fallback.

    A ``BoundStep``'s bound callable can structurally execute at most one of
    the four E4-reviewed targets (object identity in
    ``bound_configuration.resolve_trusted_call`` is exclusive), so trying
    each classifier in turn and taking the first non-``Uncertified`` result
    is exhaustive and unambiguous -- never a "closest match" heuristic.
    """
    formula_certificate = classify_formula_helper_step(step)
    if not isinstance(formula_certificate, Uncertified):
        return _handle_formula_helper(frames, state, step, formula_certificate)

    grouped_certificate = classify_grouped_producer_step(step)
    if not isinstance(grouped_certificate, Uncertified):
        return _handle_grouped_producer(frames, state, step, grouped_certificate)

    expand_certificate = classify_expand_grouped_step(step)
    if not isinstance(expand_certificate, Uncertified):
        return _handle_expand_grouped(frames, state, step, expand_certificate)

    manifest_certificate = classify_artifact_manifest_step(step)
    if not isinstance(manifest_certificate, Uncertified):
        return _handle_artifact_manifest(frames, state, step, manifest_certificate)

    return _fallback_uncertified(frames, step)


def run_managed_steps(
    frames: Frames, state: ManagedExecutionState, steps: Iterable[BoundStep]
) -> tuple[Frames, ManagedExecutionState]:
    """Apply :func:`execute_managed_step` to every step in declared order."""
    for step in steps:
        frames, state = execute_managed_step(frames, state, step)
    return frames, state


# ---------------------------------------------------------------------------
# Final cleanup / sink authorization
# ---------------------------------------------------------------------------


def _extract_sheet_renames(meta: object) -> dict[str, str]:
    """Old-frame-name -> new-sheet-name map from ``_meta.workbook_view.sheets``.

    Local, non-validating shape reading only -- ``workbook_view`` selection,
    validation, and rename application remain owned by
    ``rendering.frame_selection.select_render_frames``; this only answers
    "is the nested FormulaSpec role's referenced lookup sheet one of the
    names being renamed" (FTR section 11, compatibility rule B) before
    renderer entry. Any unrecognized/malformed shape yields no renames here
    (that malformed-shape rejection remains the family's own concern).
    """
    if not isinstance(meta, dict):
        return {}
    view = meta.get("workbook_view")
    if not isinstance(view, dict):
        return {}
    sheets = view.get("sheets")
    if not isinstance(sheets, list):
        return {}
    renames: dict[str, str] = {}
    for entry in sheets:
        if not isinstance(entry, dict):
            continue
        frame = entry.get("frame")
        sheet = entry.get("sheet") or frame
        if type(frame) is str and type(sheet) is str and frame != sheet:
            renames[frame] = sheet
    return renames


def _authorize_role_for_sink(role: ControlledRole, *, sink_kind: str, meta: object) -> None:
    if type(role) in (GroupedMatrixRole, GroupedMatrixFormulaRole, LookupFormulaSpecRole):
        if sink_kind not in FORMULA_CAPABLE_SINK_KINDS:
            raise UnauthorizedControlledRoleAtSinkError(
                role_kind=type(role).__name__, frame=role.frame, sink_kind=sink_kind
            )
        if type(role) is GroupedMatrixFormulaRole:
            rejection = reject_referenced_lookup_sheet_rename(
                role, sheet_renames=_extract_sheet_renames(meta)
            )
            if rejection is not None:
                raise UnauthorizedControlledRoleAtSinkError(
                    role_kind=type(role).__name__, frame=role.frame, sink_kind=sink_kind
                )
        return
    if type(role) is ArtifactManifestSourceFramesRole:
        if sink_kind != MANIFEST_ADAPTER_SINK_KIND:
            raise UnauthorizedControlledRoleAtSinkError(
                role_kind=type(role).__name__, frame=role.frame, sink_kind=sink_kind
            )
        return
    raise UnauthorizedControlledRoleAtSinkError(
        role_kind=type(role).__name__, frame=getattr(role, "frame", "<unknown>"), sink_kind=sink_kind
    )


def finalize_managed_state(
    frames_before_cleanup: Frames,
    frames_after_cleanup: Frames,
    state: ManagedExecutionState,
    *,
    sink_kind: str,
) -> Frames:
    """Terminate cleaned-up roles, then authorize every surviving role for
    ``sink_kind`` before the caller may invoke the saver (FTR section 14).

    Raises :class:`UnauthorizedControlledRoleAtSinkError` -- before this
    function returns, so before any saver runs -- when a controlled role
    remains live at a sink kind that has no exact reviewed consuming
    transition. Whole-frame final cleanup (``_meta.pipeline_cleanup``) is the
    only other recognized exit besides an exact capable-adapter sink.
    """
    removed_frames = frozenset(frames_before_cleanup) - frozenset(frames_after_cleanup)
    surviving_roles = terminate_roles_removed_by_cleanup(state.roles, removed_frames=removed_frames)
    meta = frames_after_cleanup.get("_meta") if isinstance(frames_after_cleanup, Mapping) else None
    for role in surviving_roles:
        _authorize_role_for_sink(role, sink_kind=sink_kind, meta=meta)
    return frames_after_cleanup
