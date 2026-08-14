"""Trusted Ingress YAML Option A: reserved ``_meta`` sidecar in ``yaml_dir``.

`FTR-TRUSTED-INGRESS-P4A` section 11 ("YAML reserved metadata-sidecar
decision"), accepted unchanged by the E3 metadata census: the stem ``_meta``
is reserved in a YAML directory input. At most one of ``_meta.yaml``/
``_meta.yml`` may be present; the backend safe-loads it and places the mapping
directly at ``Frames["_meta"]`` -- it is never materialized as an ordinary
DataFrame sheet. A non-mapping root or both spellings present is rejected at
this backend/parse boundary, before Domain ingress (E3) ever runs. Domain
ingress (E3) substrate admission of the loaded mapping is covered separately
in ``tests/unit/domain/ingress/test_metadata_admission.py`` and the
integration boundary suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spreadsheet_handling.io_backends.yaml_backend import load_yaml_dir

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


def _write(path: Path, name: str, content: str) -> None:
    (path / name).write_text(content, encoding="utf-8")


def test_meta_yaml_sidecar_is_loaded_as_mapping_not_a_sheet(tmp_path: Path):
    _write(tmp_path, "products.yml", "- id: 1\n  name: a\n")
    _write(tmp_path, "_meta.yaml", "legend_blocks: {}\nauto_filter: true\n")

    frames = load_yaml_dir(str(tmp_path))

    assert frames["_meta"] == {"legend_blocks": {}, "auto_filter": True}
    assert type(frames["_meta"]) is dict
    assert set(frames) == {"products", "_meta"}


def test_meta_yml_spelling_is_also_recognized(tmp_path: Path):
    _write(tmp_path, "products.yml", "- id: 1\n")
    _write(tmp_path, "_meta.yml", "auto_filter: true\n")

    frames = load_yaml_dir(str(tmp_path))

    assert frames["_meta"] == {"auto_filter": True}


def test_absent_meta_sidecar_leaves_meta_key_absent(tmp_path: Path):
    _write(tmp_path, "products.yml", "- id: 1\n")

    frames = load_yaml_dir(str(tmp_path))

    assert "_meta" not in frames


def test_both_meta_spellings_present_is_rejected(tmp_path: Path):
    _write(tmp_path, "_meta.yaml", "a: 1\n")
    _write(tmp_path, "_meta.yml", "a: 1\n")

    with pytest.raises(ValueError, match="ambiguous"):
        load_yaml_dir(str(tmp_path))


@pytest.mark.parametrize(
    "content",
    ["- 1\n- 2\n", "just a string\n", "42\n"],
    ids=["list_root", "string_root", "number_root"],
)
def test_non_mapping_meta_root_is_rejected(tmp_path: Path, content: str):
    _write(tmp_path, "_meta.yaml", content)

    with pytest.raises(ValueError, match="must be a mapping"):
        load_yaml_dir(str(tmp_path))


def test_empty_meta_sidecar_file_is_rejected(tmp_path: Path):
    _write(tmp_path, "_meta.yaml", "")

    with pytest.raises(ValueError, match="must be a mapping"):
        load_yaml_dir(str(tmp_path))


def test_meta_sidecar_load_does_not_run_e3_admission_itself(tmp_path: Path):
    # The backend boundary only owns the parse-boundary mapping-shape fact;
    # full recursive substrate admission is Domain ingress's (E3) job. A
    # mapping-shaped but E3-invalid candidate (non-str key) must still load
    # successfully here.
    _write(tmp_path, "_meta.yaml", "1: x\n")

    frames = load_yaml_dir(str(tmp_path))

    assert frames["_meta"] == {1: "x"}
