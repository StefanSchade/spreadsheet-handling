from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest


pytestmark = pytest.mark.ftr("FTR-COLUMN-WIDTH-ROUNDTRIP-P4")


def test_xlsx_import_paths_do_not_require_optional_odf_dependency():
    script = textwrap.dedent(
        """
        import importlib.abc
        import sys


        class BlockOdf(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "odf" or fullname.startswith("odf."):
                    raise ModuleNotFoundError("blocked optional odf dependency")
                return None


        sys.meta_path.insert(0, BlockOdf())

        import spreadsheet_handling.io_backends as backends
        from spreadsheet_handling.io_backends import ExcelBackend
        from spreadsheet_handling.io_backends.router import get_loader, get_saver
        from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend as DirectExcelBackend

        assert ExcelBackend is DirectExcelBackend
        assert callable(backends.make_backend)
        assert callable(get_loader("xlsx"))
        assert callable(get_saver("xlsx"))
        assert callable(get_loader("ods"))
        assert callable(get_saver("ods"))
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
