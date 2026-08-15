"""Phase-E slice E6 -- programmatic-surface contract and API publication.

Authority: ``docs/backlog/FTR-TRUSTED-INGRESS-P4A.adoc`` section 23 ("E6 --
programmatic-surface contract and API publication") and section 46
(implementation evidence). E6 is a publication decision, not a behavior
change: consumer evidence (this repository's own tests, the demo-consumer
smoke suite, and ``docs/ai_info/interfaces_and_gates.adoc``) showed every
maintained programmatic caller already reaches Trusted Ingress through the
framework-managed entry points (``orchestrate``, ``run_app``,
``run_schema_maintenance``), so E6 selected Decision C: publish the
contract, add no new explicit conformance-establishment helper.

These tests pin exactly the claims E6 publishes:

* ``run_pipeline`` performs no automatic ingress -- a non-conformant
  candidate that ``domain.ingress``/``application.managed_pipeline`` reject
  passes through it unchanged (contrast with the framework-managed seam).
* the framework-managed seam (``application.managed_pipeline.
  establish_initial_state``, which ``orchestrate`` calls first) rejects the
  same candidate.
* documented public imports resolve from their promised paths.
* internal/importable-only surfaces (``domain.ingress``,
  ``pipeline.execution_state``) are not promoted through any package
  aggregate export.
* no new public conformance-establishment helper was added (Decision C).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _unsupported_top_level_candidate() -> dict[str, object]:
    # Not a DataFrame/ExactTable/"_meta" entry -- rejected by E2 structural
    # admission (``unsupported_top_level_carrier``), independently of any
    # cell content.
    return {"bad": object()}


# ---------------------------------------------------------------------------
# run_pipeline stays unwired: it accepts what the managed seam rejects.
# ---------------------------------------------------------------------------


def test_run_pipeline_performs_no_automatic_ingress_establishment() -> None:
    from spreadsheet_handling.pipeline.execution import run_pipeline
    from spreadsheet_handling.pipeline.types import BoundStep

    calls: list[str] = []

    def identity(frames):
        calls.append("touched")
        return frames

    candidate = _unsupported_top_level_candidate()
    step = BoundStep(name="identity", config={}, fn=identity)

    result = run_pipeline(candidate, [step])

    assert calls == ["touched"]
    assert result is candidate


def test_domain_ingress_rejects_the_same_candidate_run_pipeline_accepted() -> None:
    from spreadsheet_handling.domain.ingress import run_domain_ingress
    from spreadsheet_handling.domain.ingress.structural_admission import (
        OrdinaryStructureAdmissionError,
    )

    with pytest.raises(OrdinaryStructureAdmissionError):
        run_domain_ingress(_unsupported_top_level_candidate())


def test_managed_seam_establish_initial_state_rejects_the_same_candidate() -> None:
    """The exact call ``orchestrate`` makes first, before any configured step."""
    from spreadsheet_handling.application.managed_pipeline import establish_initial_state
    from spreadsheet_handling.domain.ingress.structural_admission import (
        OrdinaryStructureAdmissionError,
    )

    with pytest.raises(OrdinaryStructureAdmissionError):
        establish_initial_state(_unsupported_top_level_candidate())


# ---------------------------------------------------------------------------
# Documented public imports resolve from their promised paths.
# ---------------------------------------------------------------------------


def test_framework_managed_entry_points_resolve() -> None:
    from spreadsheet_handling.application.orchestrator import orchestrate
    from spreadsheet_handling.application.schema_maintenance import run_schema_maintenance
    from spreadsheet_handling.orchestrator import orchestrate as shim_orchestrate
    from spreadsheet_handling.pipeline import run_app

    assert callable(orchestrate)
    assert callable(run_app)
    assert callable(run_schema_maintenance)
    assert shim_orchestrate is orchestrate


def test_caller_precondition_surfaces_resolve() -> None:
    from spreadsheet_handling.pipeline import (
        build_steps_from_config,
        build_steps_from_yaml,
        run_pipeline,
    )
    from spreadsheet_handling.pipeline.steps import (
        make_apply_fks_step,
        make_apply_overrides_step,
        make_bootstrap_meta_step,
        make_drop_helpers_step,
        make_identity_step,
        make_validate_step,
    )

    for candidate in (
        build_steps_from_config,
        build_steps_from_yaml,
        run_pipeline,
        make_identity_step,
        make_validate_step,
        make_apply_fks_step,
        make_drop_helpers_step,
        make_bootstrap_meta_step,
        make_apply_overrides_step,
    ):
        assert callable(candidate)


def test_direct_backend_surface_resolves() -> None:
    from spreadsheet_handling.io_backends import BackendBase, make_backend

    assert callable(make_backend)
    assert isinstance(BackendBase(), BackendBase)


# ---------------------------------------------------------------------------
# No aggregate importability promotion; internal surfaces stay internal.
# ---------------------------------------------------------------------------


def test_domain_and_application_packages_export_no_barrel() -> None:
    import spreadsheet_handling.application as application_pkg
    import spreadsheet_handling.domain as domain_pkg

    assert not hasattr(domain_pkg, "__all__")
    assert not hasattr(application_pkg, "__all__")
    # No incidental re-export of the managed seam's internals at package level.
    assert not hasattr(domain_pkg, "run_domain_ingress")
    assert not hasattr(application_pkg, "orchestrate")


def test_top_level_package_publishes_only_version() -> None:
    import spreadsheet_handling as top_level_pkg

    assert top_level_pkg.__all__ == ["__version__"]


def test_execution_state_is_not_reexported_from_pipeline_or_application() -> None:
    import spreadsheet_handling.application as application_pkg
    import spreadsheet_handling.pipeline as pipeline_pkg

    assert "execution_state" not in pipeline_pkg.__all__
    assert not hasattr(pipeline_pkg, "ManagedExecutionState")
    assert not hasattr(application_pkg, "ManagedExecutionState")


# ---------------------------------------------------------------------------
# Decision C: no new explicit conformance-establishment helper was added.
# ---------------------------------------------------------------------------


def test_no_new_explicit_conformance_establishment_helper_was_added() -> None:
    import spreadsheet_handling.application as application_pkg
    import spreadsheet_handling.domain.ingress as ingress_pkg
    import spreadsheet_handling.pipeline as pipeline_pkg

    for candidate_name in ("establish_ingress_conformance", "establish_conformance"):
        assert not hasattr(ingress_pkg, candidate_name)
        assert not hasattr(pipeline_pkg, candidate_name)
        assert not hasattr(application_pkg, candidate_name)
