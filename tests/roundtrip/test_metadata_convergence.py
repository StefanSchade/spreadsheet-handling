"""Metadata convergence over repeated canonical -> workbook -> canonical cycles.

Assert that persisted ``_meta`` stabilizes after the first round trip.
Running the same cycle a second or third time without intervening data
changes must produce byte-identical ``_meta``, modulo explicitly listed
drift fields (timestamps, build stamps, etc. -- none of which are
expected in the minimal fixture).

This test prevents recurrence of the failure class observed in
``BUG-RUNTIME-META-PERSISTENCE-BOUNDARY-P4A``, where runtime-only
metadata accumulated into the persisted sidecar across runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


pytestmark = [
    pytest.mark.roundtrip,
    pytest.mark.ftr("FTR-ROUNDTRIP-TEST-LAYER-P4A"),
]


# Fields whose drift across runs is structurally expected. Empty for the
# minimal fixture (no counters, no commit stamps, no timestamps). If a
# future fixture or step introduces legitimate drift, extend this list
# with an explicit reason; do not relax the equality to "approximate".
_EXPECTED_DRIFT_PATHS: tuple[tuple[str, ...], ...] = ()


def _load_meta(reimport_dir: Path) -> dict:
    raw = (reimport_dir / "_meta.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(raw)


def _scrub(meta: dict, drift_paths: tuple[tuple[str, ...], ...]) -> dict:
    """Return a deep copy of meta with drift_paths removed.

    Each path is a tuple of dict keys; missing intermediate keys are
    silently tolerated so the scrubber stays robust against
    shape changes that are themselves the bug we want to catch.
    """
    import copy

    out = copy.deepcopy(meta)
    for path in drift_paths:
        cursor = out
        for segment in path[:-1]:
            if not isinstance(cursor, dict) or segment not in cursor:
                cursor = None
                break
            cursor = cursor[segment]
        if isinstance(cursor, dict):
            cursor.pop(path[-1], None)
    return out


def test_meta_stable_from_second_roundtrip(minimal_fk_workdir, tmp_path: Path) -> None:
    """Persisted ``_meta`` must converge by the second round trip.

    Runs three full canonical -> workbook -> canonical cycles. The
    first run establishes the persisted ``_meta`` shape from a
    canonical input that has no ``_meta.yaml`` on disk; the second
    and third runs use the previous reimport (now carrying a
    ``_meta.yaml``) as the canonical input. The invariant under test:
    the second-run ``_meta`` must equal the third-run ``_meta``.

    A failure here indicates runtime-only metadata leaking into
    persisted ``_meta`` (the failure class of
    ``BUG-RUNTIME-META-PERSISTENCE-BOUNDARY-P4A``).
    """
    # First cycle: canonical (no _meta.yaml) -> workbook -> reimport_1.
    assert minimal_fk_workdir.run_forward() == 0
    assert minimal_fk_workdir.run_reverse() == 0
    meta_after_first = _load_meta(minimal_fk_workdir.reimport)

    # Build a second working directory whose canonical input is the
    # first reimport (so _meta.yaml is now an input, exercising the
    # carry-through path that was the original failure vector).
    import shutil
    second_canonical = tmp_path / "canonical_2"
    shutil.copytree(minimal_fk_workdir.reimport, second_canonical)
    second_sheet = tmp_path / "workbook_2.xlsx"
    second_reimport = tmp_path / "reimport_2"
    _run_cycle(second_canonical, second_sheet, second_reimport)
    meta_after_second = _load_meta(second_reimport)

    # Third cycle, same shape.
    third_canonical = tmp_path / "canonical_3"
    shutil.copytree(second_reimport, third_canonical)
    third_sheet = tmp_path / "workbook_3.xlsx"
    third_reimport = tmp_path / "reimport_3"
    _run_cycle(third_canonical, third_sheet, third_reimport)
    meta_after_third = _load_meta(third_reimport)

    scrubbed_second = _scrub(meta_after_second, _EXPECTED_DRIFT_PATHS)
    scrubbed_third = _scrub(meta_after_third, _EXPECTED_DRIFT_PATHS)

    assert scrubbed_second == scrubbed_third, (
        "persisted _meta must be stable from the second roundtrip onward. "
        "If a difference appears here, inspect for runtime-only metadata "
        "leaking into the persisted carrier (the failure class of "
        "BUG-RUNTIME-META-PERSISTENCE-BOUNDARY-P4A)."
    )

    # Sanity check: the first cycle (canonical without _meta.yaml input)
    # may legitimately differ from the second (canonical with _meta.yaml
    # input). The invariant requires convergence from cycle 2 on, not
    # before. The meta_after_first variable is bound for diagnostics
    # only; do not assert against it.
    del meta_after_first


def _run_cycle(canonical: Path, sheet: Path, reimport: Path) -> None:
    """Run one canonical -> workbook -> canonical cycle through the CLI.

    Stays in this file rather than the shared conftest so the test
    keeps full control over the working directory layout for the
    three-cycle composition.
    """
    from tests.roundtrip.conftest import (
        _forward_pipeline,
        _reverse_pipeline,
        _run_cli,
        _write_yaml,
    )

    forward = sheet.parent / f"{sheet.stem}_forward.yaml"
    reverse = sheet.parent / f"{sheet.stem}_reverse.yaml"
    _write_yaml(forward, _forward_pipeline(canonical, sheet))
    _write_yaml(reverse, _reverse_pipeline(sheet, reimport))
    assert _run_cli(forward) == 0, "forward pipeline must succeed"
    assert _run_cli(reverse) == 0, "reverse pipeline must succeed"
