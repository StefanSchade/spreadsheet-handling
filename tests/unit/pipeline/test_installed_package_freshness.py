"""Installed-layer freshness guard for the retired ``project_by_role`` module.

The source-layer guard in ``test_step_registration.py`` cannot observe a stale
*installed* package, because ``pyproject.toml`` sets ``pythonpath = ["src"]`` and
pytest therefore resolves the source tree before site-packages. This guard runs
a subprocess with the active environment's Python in isolated mode (``-I``, which
ignores ``PYTHON*`` env vars and does not add the current directory to
``sys.path``), with ``PYTHONPATH`` removed and an external working directory, so
the only resolvable ``spreadsheet_handling`` is whatever the maintained
environment actually installed.

It fails if the supported ``make setup`` / ``make clean-stamps`` workflow leaves
an obsolete non-editable copy of the deleted module importable. See
``FTR-XREF-LOOKUP-HELPER-SUBSTITUTION-P4A2`` Slice 4 Correction 001
(``XREF-S4-R001-IMP-001``).
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.ftr("FTR-XREF-LOOKUP-HELPER-SUBSTITUTION-P4A2")

RETIRED_MODULE = "spreadsheet_handling.domain.transformations.project_by_role"

_PROBE = textwrap.dedent(
    """
    import importlib
    import inspect
    import json
    import os
    from importlib.metadata import distribution

    RETIRED = "spreadsheet_handling.domain.transformations.project_by_role"

    # (1) the surrounding package imports from the installed/editable layer.
    import spreadsheet_handling

    # (4) the retired module's parent package imports cleanly, so a failure to
    # import the leaf is a genuine leaf removal, not a missing parent/dependency.
    import spreadsheet_handling.domain.transformations  # noqa: F401

    # (2)+(3) the exact retired module is gone and reports exactly its own name.
    try:
        importlib.import_module(RETIRED)
    except ModuleNotFoundError as exc:
        if exc.name != RETIRED:
            raise SystemExit("WRONG_MISSING_NAME:" + repr(exc.name))
    else:
        raise SystemExit("RETIRED_MODULE_STILL_IMPORTABLE")

    # (5) the installed environment remains usable and the step is unregistered.
    from spreadsheet_handling.pipeline import REGISTRY
    if "project_by_role" in REGISTRY:
        raise SystemExit("STEP_STILL_REGISTERED")
    if len(REGISTRY) < 44:
        raise SystemExit("REGISTRY_TOO_SMALL:" + str(len(REGISTRY)))

    # Editable expectation: the maintained install resolves to the current repo
    # source, either via the editable finder or an editable direct_url record.
    pkg_file = inspect.getfile(spreadsheet_handling)
    direct_url = distribution("spreadsheet-handling").read_text("direct_url.json") or "{}"
    is_editable = json.loads(direct_url).get("dir_info", {}).get("editable") is True
    in_source_tree = (os.sep + "src" + os.sep + "spreadsheet_handling") in pkg_file
    if not (is_editable or in_source_tree):
        raise SystemExit("NOT_EDITABLE_OR_SOURCE:" + pkg_file + ":" + direct_url)

    print("INSTALLED_LAYER_OK")
    """
)


def test_retired_module_absent_in_installed_layer(tmp_path) -> None:
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "-I", "-c", _PROBE],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
    )
    assert result.returncode == 0, (
        f"installed-layer probe failed\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "INSTALLED_LAYER_OK" in result.stdout, result.stdout
