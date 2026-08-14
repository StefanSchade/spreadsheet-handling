"""Trusted Ingress E3: legacy XLSX/ODS Python-literal metadata narrowing.

`FTR-TRUSTED-INGRESS-P4A_E3_metadata_census.adoc` section 17.2 ("Exact F1
per-shape disposition") and section 18.6 (non-``str`` key disposition):
`tuple`/`set`/`bytes`/`complex` values and non-``str`` keys reachable through
the legacy pre-JSON ``str(dict)`` -> ``ast.literal_eval`` fallback
(`workbook_meta_blob`) receive *targeted rejection*, not silent coercion or
silent admission. The legacy carrier parser itself is unchanged and still
recovers the dict (compatibility preserved); Domain ingress (E3) then rejects
the unsupported node deterministically the moment ``run_domain_ingress`` sees
it, with no XLSX/ODS-specific code in E3 itself -- the same generic recursive
walker handles both backends because both parsers hand E3 an ordinary
``dict`` carrying the legacy Python-literal value/key unchanged.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from spreadsheet_handling.domain.ingress import run_domain_ingress
from spreadsheet_handling.domain.ingress.metadata_admission import (
    MetadataSubstrateAdmissionError,
)
from spreadsheet_handling.io_backends.ods.ods_backend import load_ods, save_ods
from spreadsheet_handling.io_backends.xlsx.xlsx_backend import ExcelBackend

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


# ---------------------------------------------------------------------------
# XLSX: legacy hidden-sheet ``workbook_meta_blob`` repr literal
# ---------------------------------------------------------------------------


def _write_xlsx_legacy_blob(path: Path, literal: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "products"
    ws.append(["sku"])
    ws.append(["P-1"])
    meta_ws = wb.create_sheet("_meta")
    meta_ws.sheet_state = "hidden"
    meta_ws.append(["workbook_meta_blob", literal])
    wb.save(path)
    wb.close()


@pytest.mark.parametrize(
    "literal,expected_path",
    [
        ("{'version': 'legacy', 'bad': (1, 2)}", "_meta.bad"),
        ("{'version': 'legacy', 'bad': {1, 2}}", "_meta.bad"),
        ("{'version': 'legacy', 'bad': b'hi'}", "_meta.bad"),
        ("{'version': 'legacy', 'bad': (1+2j)}", "_meta.bad"),
    ],
    ids=["tuple", "set", "bytes", "complex"],
)
def test_xlsx_legacy_special_value_is_rejected_after_recovery(
    tmp_path: Path, literal: str, expected_path: str
):
    out = tmp_path / "legacy.xlsx"
    _write_xlsx_legacy_blob(out, literal)

    # The legacy parser itself still succeeds -- compatibility preserved.
    parsed = ExcelBackend().read_multi(str(out), header_levels=1)
    assert "bad" in parsed["_meta"]

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress(parsed)
    assert excinfo.value.kind == "invalid_metadata_node"
    assert excinfo.value.metadata_path == expected_path


def test_xlsx_legacy_non_str_key_is_rejected_after_recovery(tmp_path: Path):
    out = tmp_path / "legacy-key.xlsx"
    _write_xlsx_legacy_blob(out, "{1: 'x'}")

    parsed = ExcelBackend().read_multi(str(out), header_levels=1)
    assert 1 in parsed["_meta"]

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress(parsed)
    assert excinfo.value.kind == "unsupported_metadata_key"


def test_xlsx_legacy_dict_only_literal_still_admitted_by_e3(tmp_path: Path):
    out = tmp_path / "legacy-ok.xlsx"
    _write_xlsx_legacy_blob(out, "{'version': 'legacy', 'nested': {'enabled': True}}")

    parsed = ExcelBackend().read_multi(str(out), header_levels=1)
    result = run_domain_ingress(parsed)
    assert result["_meta"] == {"version": "legacy", "nested": {"enabled": True}}


# ---------------------------------------------------------------------------
# ODS: same legacy literal recovered through the ODS hidden-sheet blob cell
# ---------------------------------------------------------------------------


def _write_ods_legacy_blob(path: Path, literal: str) -> None:
    # Write a normal ODS with a JSON blob via the real writer, then patch the
    # single blob cell (both the attribute and text-run copies) in place to
    # the legacy pre-JSON repr literal -- reproducing a workbook actually
    # written by a pre-JSON framework version without hand-authoring raw ODF
    # XML end to end.
    frames = {
        "products": pd.DataFrame({"sku": ["P-1"]}),
        "_meta": {"version": "placeholder"},
    }
    save_ods(frames, str(path))

    with zipfile.ZipFile(path) as zf:
        content = zf.read("content.xml").decode("utf-8")
        names = zf.namelist()
        data = {name: zf.read(name) for name in names}

    old_json = '{"version":"placeholder"}'
    assert old_json in content, "expected JSON blob shape not found in fixture"
    escaped_literal = literal.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    patched = content.replace(
        f"office:string-value='{old_json}'><text:p>{old_json}</text:p>",
        f'office:string-value="{escaped_literal}"><text:p>{escaped_literal}</text:p>',
    )
    assert patched != content, "patch did not match the rendered blob cell"
    data["content.xml"] = patched.encode("utf-8")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            zf.writestr(name, data[name])


@pytest.mark.parametrize(
    "literal",
    [
        "{'version': 'legacy', 'bad': (1, 2)}",
        "{'version': 'legacy', 'bad': {1, 2}}",
        "{'version': 'legacy', 'bad': (1+2j)}",
    ],
    ids=["tuple", "set", "complex"],
)
def test_ods_legacy_special_value_is_rejected_after_recovery(tmp_path: Path, literal: str):
    out = tmp_path / "legacy.ods"
    _write_ods_legacy_blob(out, literal)

    parsed = load_ods(str(out), header_levels=1)
    assert "bad" in parsed["_meta"]

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress(parsed)
    assert excinfo.value.kind == "invalid_metadata_node"


def test_ods_legacy_non_str_key_is_rejected_after_recovery(tmp_path: Path):
    out = tmp_path / "legacy-key.ods"
    _write_ods_legacy_blob(out, "{1: 'x'}")

    parsed = load_ods(str(out), header_levels=1)
    assert 1 in parsed["_meta"]

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress(parsed)
    assert excinfo.value.kind == "unsupported_metadata_key"
