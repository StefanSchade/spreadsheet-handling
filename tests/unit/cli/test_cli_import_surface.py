from __future__ import annotations

from pathlib import Path

import pytest

import spreadsheet_handling.cli as cli

pytestmark = pytest.mark.ftr("FTR-REVIEW-001-QUICK-WINS-P3")


def test_cli_package_exports_only_intentional_mains() -> None:
    assert set(cli.__all__) == {
        "run_main",
        "example_json_to_xlsx_main",
        "example_xlsx_to_json_main",
    }

    assert callable(cli.run_main)
    assert callable(cli.example_json_to_xlsx_main)
    assert callable(cli.example_xlsx_to_json_main)
    assert not hasattr(cli, "pack_main")
    assert not hasattr(cli, "unpack_main")
    assert not hasattr(cli, "pack")
    assert not hasattr(cli, "unpack")


def test_project_scripts_register_current_cli_surface_only() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "sheets-run" in pyproject
    assert "sheets-example-json-to-xlsx" in pyproject
    assert "sheets-example-xlsx-to-json" in pyproject
    assert "sheets-pack" not in pyproject
    assert "sheets-unpack" not in pyproject


def test_sheets_run_entry_point_routes_through_cli_entry() -> None:
    """Regression guard for FTR-CLI-INTERRUPT-ERROR-UX-P5.

    The installed `sheets-run` console script must invoke `cli_entry`,
    not `main` directly. Routing through `cli_entry -> run_cli -> main`
    is what delivers the short `Error: ...` message, the
    `Interrupted by user.` Ctrl+C path, and exit code 130. Pinning the
    exact target prevents an accidental revert to a `main`-direct
    binding from going unnoticed.
    """
    import tomllib

    pyproject_data = tomllib.loads(
        Path("pyproject.toml").read_text(encoding="utf-8")
    )
    scripts = pyproject_data["project"]["scripts"]

    assert scripts["sheets-run"] == "spreadsheet_handling.cli.apps.run:cli_entry"

    from spreadsheet_handling.cli.apps.run import cli_entry

    assert callable(cli_entry)
