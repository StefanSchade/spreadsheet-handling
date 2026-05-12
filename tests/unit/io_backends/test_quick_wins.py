from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.base import BackendOptions, coerce_backend_options
from spreadsheet_handling.io_backends.xml_backend import XMLBackend
from spreadsheet_handling.io_backends.yaml_backend import save_yaml_dir

pytestmark = pytest.mark.ftr("FTR-REVIEW-001-QUICK-WINS-P3")


def test_coerce_backend_options_none_returns_backend_options() -> None:
    options = coerce_backend_options(None)

    assert isinstance(options, BackendOptions)
    assert options.extra == {}


def test_yaml_writer_skips_meta_sidecar(tmp_path: Path) -> None:
    frames = {
        "products": pd.DataFrame([{"id": "P1", "name": "Widget"}]),
        "_meta": {"sheets": {"products": {"freeze_header": True}}},
    }

    save_yaml_dir(frames, str(tmp_path))

    assert (tmp_path / "products.yml").exists()
    assert not (tmp_path / "_meta.yml").exists()


def test_xml_writer_skips_meta_sidecar(tmp_path: Path) -> None:
    frames = {
        "products": pd.DataFrame([{"id": "P1", "name": "Widget"}]),
        "_meta": {"sheets": {"products": {"freeze_header": True}}},
    }

    XMLBackend().write_multi(frames, str(tmp_path))

    assert (tmp_path / "products.xml").exists()
    assert not (tmp_path / "_meta.xml").exists()

    root = ET.parse(tmp_path / "products.xml").getroot()
    assert root.tag == "products"
