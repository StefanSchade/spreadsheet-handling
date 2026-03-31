"""Smoke tests for FTR-ADAPTER-DEPRECATION-STUBS: deprecated adapters raise typed errors."""
from __future__ import annotations

import pytest

from spreadsheet_handling.io_backends.errors import DeprecatedAdapterError
from spreadsheet_handling.io_backends.ods_backend import ODSBackend
from spreadsheet_handling.io_backends import make_backend

pytestmark = pytest.mark.ftr("FTR-ADAPTER-DEPRECATION-STUBS")


# ---------------------------------------------------------------------------
# ODS backend stubs
# ---------------------------------------------------------------------------

class TestODSBackendStub:
    def test_ods_read_raises_deprecated_error(self):
        backend = ODSBackend()
        with pytest.raises(DeprecatedAdapterError, match="ods.*deprecated"):
            backend.read("dummy.ods", header_levels=1)

    def test_ods_write_raises_deprecated_error(self):
        backend = ODSBackend()
        with pytest.raises(DeprecatedAdapterError, match="ods.*deprecated"):
            import pandas as pd
            backend.write(pd.DataFrame(), "dummy.ods")

    def test_ods_error_carries_adapter_name(self):
        backend = ODSBackend()
        with pytest.raises(DeprecatedAdapterError) as exc_info:
            backend.read("dummy.ods", header_levels=1)
        assert exc_info.value.adapter == "ods"

    def test_ods_error_carries_hint(self):
        backend = ODSBackend()
        with pytest.raises(DeprecatedAdapterError) as exc_info:
            backend.read("dummy.ods", header_levels=1)
        assert "XLSX" in exc_info.value.hint or "JSON" in exc_info.value.hint

    def test_ods_error_is_not_implemented_error(self):
        """DeprecatedAdapterError is a subclass of NotImplementedError for backward compat."""
        backend = ODSBackend()
        with pytest.raises(NotImplementedError):
            backend.read("dummy.ods", header_levels=1)


# ---------------------------------------------------------------------------
# excel_xlsxwriter deprecation
# ---------------------------------------------------------------------------

class TestExcelXlsxwriterDeprecation:
    def test_import_emits_deprecation_warning(self):
        with pytest.warns(DeprecationWarning, match="excel_xlsxwriter.*deprecated"):
            import importlib
            import spreadsheet_handling.io_backends.excel_xlsxwriter as mod
            importlib.reload(mod)

    def test_raises_function_available(self):
        """The _raise() helper raises DeprecatedAdapterError."""
        with pytest.warns(DeprecationWarning):
            import importlib
            import spreadsheet_handling.io_backends.excel_xlsxwriter as mod
            importlib.reload(mod)
        with pytest.raises(DeprecatedAdapterError, match="xlsxwriter"):
            mod._raise()


# ---------------------------------------------------------------------------
# Factory integration
# ---------------------------------------------------------------------------

class TestFactoryIntegration:
    def test_make_backend_ods_returns_stub(self):
        backend = make_backend("ods")
        assert isinstance(backend, ODSBackend)

    def test_make_backend_ods_raises_on_use(self):
        backend = make_backend("ods")
        with pytest.raises(DeprecatedAdapterError):
            backend.read("dummy.ods", header_levels=1)

    def test_make_backend_active_still_works(self):
        """Active backends are unaffected."""
        for kind in ("xlsx", "json", "csv", "xml"):
            backend = make_backend(kind)
            assert backend is not None

    def test_make_backend_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            make_backend("foobar")
