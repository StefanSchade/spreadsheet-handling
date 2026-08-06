"""Opt-in real-LibreOffice interoperability check for ODS formula-mode FK
helpers.

BUG-ODS-XLOOKUP-FORMULA-INTEROP-P4A: an unqualified `of:=XLOOKUP(...)`
formula opens as `#NAME?` in LibreOffice Calc even though the arguments and
ranges are correct; the ODS renderer now emits the LibreOffice-qualified
`of:=COM.MICROSOFT.XLOOKUP(...)` identifier instead (see
`_ods_lookup_formula` in `odf_renderer.py`).

Unit tests (`test_ods_formula_translation.py`) and the archive-level
assertions here already prove the *serialized* formula string. This module
is the interoperability proof: it drives a real headless LibreOffice
process over the UNO bridge and proves the formula is *accepted and
evaluated*, not only that the ODS archive can be parsed.

This test is opt-in and self-skipping:

* it requires `soffice` on PATH;
* it requires a *system* python3 with the `uno` module importable (the
  `python3-uno` package) -- this is normally absent from the project's
  virtualenv, since `uno` is not pip-installable, so the actual UNO
  interaction is delegated to `tests/utils/libreoffice_uno_probe.py` run
  under that system interpreter, not under this venv's pytest process.

Excluded from the default `make test` slice via `@pytest.mark.slow`. Run
explicitly with:

    pytest tests/integration/io_backends/ods/test_ods_libreoffice_interop.py -m libreoffice -v
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from spreadsheet_handling.core.formulas import lookup_formula
from spreadsheet_handling.io_backends.ods.odf_renderer import render_workbook
from spreadsheet_handling.rendering.plan import DefineSheet, RenderPlan, SetHeader, WriteDataBlock

pytestmark = [pytest.mark.ftr("BUG-ODS-XLOOKUP-FORMULA-INTEROP-P4A"), pytest.mark.slow]

_PROBE_SCRIPT = Path(__file__).resolve().parents[3] / "utils" / "libreoffice_uno_probe.py"


def _system_python3_has_uno(python3: str) -> bool:
    try:
        result = subprocess.run(
            [python3, "-c", "import uno"],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("localhost", 0))
        return probe.getsockname()[1]


def _build_dino_insel_shape(tmp_path: Path) -> Path:
    """Reproduces the Dino-Insel `Places` / `Regions` helper shape from the
    BUG's user-observed reproduction: two lookup result fields
    (`_regions_name`, `_regions_kind`) fed by one source FK column
    (`region_id`)."""
    name_formula = lookup_formula(
        source_key_column="region_id",
        lookup_sheet="Regions",
        lookup_key_column="id",
        lookup_value_column="name",
    )
    kind_formula = lookup_formula(
        source_key_column="region_id",
        lookup_sheet="Regions",
        lookup_key_column="id",
        lookup_value_column="kind",
    )
    plan = RenderPlan()
    plan.add(DefineSheet("Places", 0))
    plan.add(SetHeader("Places", 1, 1, "id"))
    plan.add(SetHeader("Places", 1, 2, "region_id"))
    plan.add(SetHeader("Places", 1, 3, "_regions_name"))
    plan.add(SetHeader("Places", 1, 4, "_regions_kind"))
    plan.add(
        WriteDataBlock("Places", 2, 1, (("P-1", "R-1", name_formula, kind_formula),))
    )
    plan.add(DefineSheet("Regions", 1))
    plan.add(SetHeader("Regions", 1, 1, "id"))
    plan.add(SetHeader("Regions", 1, 2, "name"))
    plan.add(SetHeader("Regions", 1, 3, "kind"))
    plan.add(
        WriteDataBlock(
            "Regions",
            2,
            1,
            (
                ("R-1", "Dino Valley", "lowland"),
                ("R-2", "Fern Ridge", "highland"),
            ),
        )
    )

    out = tmp_path / "dino_insel_lookup.ods"
    render_workbook(plan, out)
    return out


@pytest.mark.libreoffice
def test_ods_formula_mode_evaluates_immediately_in_real_libreoffice(
    tmp_path: Path,
) -> None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        pytest.skip("soffice/libreoffice not found on PATH")

    python3 = shutil.which("python3") or sys.executable
    if not _system_python3_has_uno(python3):
        pytest.skip(f"system python3 ({python3}) has no importable 'uno' module")

    ods_path = _build_dino_insel_shape(tmp_path)
    port = _free_tcp_port()
    profile_dir = tmp_path / "lo_profile"
    profile_dir.mkdir()

    # Helper cells: Places!C2 (_regions_name, col=2 row=1) and
    # Places!D2 (_regions_kind, col=3 row=1), 0-based. FK cell: Places!B2
    # (region_id, col=1 row=1).
    spec = {
        "sheet": "Places",
        "cells": [[2, 1], [3, 1]],
        "edits": [
            [1, 1, "R-UNKNOWN"],
            [1, 1, "R-2"],
        ],
    }

    soffice_proc = subprocess.Popen(
        [
            soffice,
            "--headless",
            "--invisible",
            "--nocrashreport",
            "--nodefault",
            "--norestore",
            "--nologo",
            "--nofirststartwizard",
            f"-env:UserInstallation=file://{profile_dir}",
            f"--accept=socket,host=localhost,port={port};urp;",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        probe = subprocess.run(
            [python3, str(_PROBE_SCRIPT), str(ods_path), str(port), json.dumps(spec)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert probe.returncode == 0, (
            f"LibreOffice UNO probe failed:\nstdout={probe.stdout}\nstderr={probe.stderr}"
        )
        report = json.loads(probe.stdout)
    finally:
        soffice_proc.terminate()
        try:
            soffice_proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            soffice_proc.kill()
            soffice_proc.wait(timeout=15)

    initial = report["initial"]
    # No `#NAME?` on initial evaluation; correct visible lookup value.
    assert initial[0]["string"] == "Dino Valley"
    assert initial[1]["string"] == "lowland"
    assert initial[0]["error"] == 0
    assert initial[1]["error"] == 0

    unknown_key, recalculated = report["after_edits"]
    # Configured missing result (empty string default) for an unknown key.
    assert unknown_key[0]["string"] == ""
    assert unknown_key[1]["string"] == ""
    assert unknown_key[0]["error"] == 0
    assert unknown_key[1]["error"] == 0
    # Source-FK edit causes recalculation to the new key's values.
    assert recalculated[0]["string"] == "Fern Ridge"
    assert recalculated[1]["string"] == "highland"
