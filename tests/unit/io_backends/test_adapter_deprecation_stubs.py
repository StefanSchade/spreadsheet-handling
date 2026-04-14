"""Smoke tests for backend factory after deprecated adapter removal."""
from __future__ import annotations

import pytest

from spreadsheet_handling.io_backends import make_backend

pytestmark = pytest.mark.ftr("FTR-ADAPTER-DEPRECATION-STUBS")


class TestFactoryIntegration:
    def test_make_backend_active_still_works(self):
        """Active backends are unaffected."""
        for kind in ("xlsx", "ods", "json", "csv", "xml"):
            backend = make_backend(kind)
            assert backend is not None

    def test_make_backend_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            make_backend("foobar")

    def test_make_backend_calc_alias_resolves(self):
        backend = make_backend("calc")
        assert backend is not None
