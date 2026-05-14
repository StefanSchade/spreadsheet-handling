"""Tests for the key-value resource file writer (FTR-KEY-VALUE-RESOURCE-WRITER-P4A)."""
from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.key_value_writer import write_key_value_resources
from spreadsheet_handling.pipeline import REGISTRY, build_steps_from_config, run_pipeline
from spreadsheet_handling.pipeline.types import StepRegistration

pytestmark = pytest.mark.ftr("FTR-KEY-VALUE-RESOURCE-WRITER-P4A")


def test_single_file_writes_key_value_pairs(tmp_path: pytest.TempPathFactory) -> None:
    frames = {
        "resources": pd.DataFrame([
            {"key": "app.name", "value": "MyApp"},
            {"key": "app.version", "value": "1.0"},
        ])
    }

    out = write_key_value_resources(
        frames,
        source="resources",
        output_dir=tmp_path,
        file_pattern="messages.properties",
        key="key",
        value="value",
    )

    content = (tmp_path / "messages.properties").read_text(encoding="utf-8")
    assert content == "app.name=MyApp\napp.version=1.0\n"
    assert "resources" in out


def test_sort_by_produces_deterministic_order(tmp_path: pytest.TempPathFactory) -> None:
    frames = {
        "resources": pd.DataFrame([
            {"key": "z.label", "value": "Z"},
            {"key": "a.label", "value": "A"},
            {"key": "m.label", "value": "M"},
        ])
    }

    write_key_value_resources(
        frames,
        source="resources",
        output_dir=tmp_path,
        file_pattern="messages.properties",
        key="key",
        value="value",
        sort_by="key",
    )

    content = (tmp_path / "messages.properties").read_text(encoding="utf-8")
    assert content == "a.label=A\nm.label=M\nz.label=Z\n"


def test_partition_by_column_writes_one_file_per_group(tmp_path: pytest.TempPathFactory) -> None:
    frames = {
        "resources": pd.DataFrame([
            {"locale": "en", "key": "greeting", "value": "Hello"},
            {"locale": "de", "key": "greeting", "value": "Hallo"},
            {"locale": "en", "key": "farewell", "value": "Goodbye"},
            {"locale": "de", "key": "farewell", "value": "Tschüss"},
        ])
    }

    out = write_key_value_resources(
        frames,
        source="resources",
        output_dir=tmp_path,
        file_pattern="{locale}/messages.properties",
        key="key",
        value="value",
        sort_by="key",
    )

    en = (tmp_path / "en" / "messages.properties").read_text(encoding="utf-8")
    de = (tmp_path / "de" / "messages.properties").read_text(encoding="utf-8")
    assert en == "farewell=Goodbye\ngreeting=Hello\n"
    assert de == "farewell=Tsch\\u00fcss\ngreeting=Hallo\n"

    report = out["key_value_resource_files"]
    assert set(report["path"]) == {"en/messages.properties", "de/messages.properties"}


def test_unicode_escaping_encodes_non_ascii_as_backslash_u(tmp_path: pytest.TempPathFactory) -> None:
    frames = {
        "resources": pd.DataFrame([
            {"key": "label", "value": "Ü"},
        ])
    }

    write_key_value_resources(
        frames,
        source="resources",
        output_dir=tmp_path,
        file_pattern="out.properties",
        key="key",
        value="value",
        properties_escaping="unicode",
    )

    content = (tmp_path / "out.properties").read_text(encoding="utf-8")
    assert content == "label=\\u00dc\n"


def test_utf8_escaping_writes_raw_unicode(tmp_path: pytest.TempPathFactory) -> None:
    frames = {
        "resources": pd.DataFrame([
            {"key": "label", "value": "Ü"},
        ])
    }

    write_key_value_resources(
        frames,
        source="resources",
        output_dir=tmp_path,
        file_pattern="out.properties",
        key="key",
        value="value",
        properties_escaping="utf-8",
    )

    content = (tmp_path / "out.properties").read_text(encoding="utf-8")
    assert content == "label=Ü\n"


def test_duplicate_key_in_same_file_raises_clear_error(tmp_path: pytest.TempPathFactory) -> None:
    frames = {
        "resources": pd.DataFrame([
            {"key": "greeting", "value": "Hello"},
            {"key": "greeting", "value": "Hi"},
        ])
    }

    with pytest.raises(ValueError, match="duplicate key.*greeting"):
        write_key_value_resources(
            frames,
            source="resources",
            output_dir=tmp_path,
            file_pattern="out.properties",
            key="key",
            value="value",
        )


def test_path_traversal_is_rejected(tmp_path: pytest.TempPathFactory) -> None:
    frames = {
        "resources": pd.DataFrame([
            {"locale": "../evil", "key": "x", "value": "y"},
        ])
    }

    with pytest.raises(ValueError, match="escapes output_dir"):
        write_key_value_resources(
            frames,
            source="resources",
            output_dir=tmp_path,
            file_pattern="{locale}/messages.properties",
            key="key",
            value="value",
        )


def test_report_frame_contains_one_row_per_file(tmp_path: pytest.TempPathFactory) -> None:
    frames = {
        "resources": pd.DataFrame([
            {"locale": "en", "key": "a", "value": "A"},
            {"locale": "fr", "key": "a", "value": "B"},
        ])
    }

    out = write_key_value_resources(
        frames,
        source="resources",
        output_dir=tmp_path,
        file_pattern="{locale}.properties",
        key="key",
        value="value",
        report_frame="my_report",
    )

    assert "my_report" in out
    report = out["my_report"]
    assert list(report.columns) == ["path", "frame", "rows", "bytes"]
    assert len(report) == 2
    assert set(report["path"]) == {"en.properties", "fr.properties"}
    assert all(report["frame"] == "resources")
    assert all(report["rows"] == 1)


def test_missing_key_column_raises_clear_error(tmp_path: pytest.TempPathFactory) -> None:
    frames = {
        "resources": pd.DataFrame([{"value": "Hello"}])
    }

    with pytest.raises(KeyError, match="missing columns"):
        write_key_value_resources(
            frames,
            source="resources",
            output_dir=tmp_path,
            file_pattern="out.properties",
            key="key",
            value="value",
        )


def test_special_chars_in_key_are_escaped(tmp_path: pytest.TempPathFactory) -> None:
    frames = {
        "resources": pd.DataFrame([
            {"key": "key=with=equals", "value": "v1"},
            {"key": "key:with:colon", "value": "v2"},
        ])
    }

    write_key_value_resources(
        frames,
        source="resources",
        output_dir=tmp_path,
        file_pattern="out.properties",
        key="key",
        value="value",
        sort_by="key",
    )

    content = (tmp_path / "out.properties").read_text(encoding="utf-8")
    assert "key\\=with\\=equals=v1" in content
    assert "key\\:with\\:colon=v2" in content


def test_step_is_config_addressable(tmp_path: pytest.TempPathFactory) -> None:
    frames = {
        "labels": pd.DataFrame([
            {"k": "title", "v": "Hello"},
            {"k": "body",  "v": "World"},
        ])
    }

    steps = build_steps_from_config([{
        "step": "write_key_value_resources",
        "source": "labels",
        "output_dir": str(tmp_path),
        "file_pattern": "labels.properties",
        "key": "k",
        "value": "v",
    }])

    assert isinstance(REGISTRY["write_key_value_resources"], StepRegistration)
    assert steps[0].config["target"].endswith(":write_key_value_resources")

    out = run_pipeline(frames, steps)
    content = (tmp_path / "labels.properties").read_text(encoding="utf-8")
    assert "title=Hello" in content
    assert "body=World" in content
    assert "key_value_resource_files" in out


def test_reordered_input_rows_produce_identical_file_contents(tmp_path: pytest.TempPathFactory) -> None:
    rows = [
        {"locale": "de", "key": "greeting", "value": "Hallo"},
        {"locale": "en", "key": "greeting", "value": "Hello"},
        {"locale": "de", "key": "farewell", "value": "Tschüss"},
        {"locale": "en", "key": "farewell", "value": "Goodbye"},
    ]
    frames_a = {"res": pd.DataFrame(rows)}
    frames_b = {"res": pd.DataFrame(list(reversed(rows)))}

    kwargs = dict(
        source="res",
        output_dir=str(tmp_path / "a"),
        file_pattern="{locale}.properties",
        key="key",
        value="value",
        sort_by="key",
    )
    write_key_value_resources(frames_a, **kwargs)
    write_key_value_resources(frames_b, **{**kwargs, "output_dir": str(tmp_path / "b")})

    for locale in ("en", "de"):
        content_a = (tmp_path / "a" / f"{locale}.properties").read_text(encoding="utf-8")
        content_b = (tmp_path / "b" / f"{locale}.properties").read_text(encoding="utf-8")
        assert content_a == content_b, f"{locale}: contents differ between orderings"


def test_report_frame_order_is_stable_regardless_of_input_row_order(tmp_path: pytest.TempPathFactory) -> None:
    rows = [
        {"locale": "fr", "key": "a", "value": "1"},
        {"locale": "en", "key": "a", "value": "2"},
        {"locale": "de", "key": "a", "value": "3"},
    ]
    frames_a = {"res": pd.DataFrame(rows)}
    frames_b = {"res": pd.DataFrame(list(reversed(rows)))}

    out_a = write_key_value_resources(
        frames_a, source="res", output_dir=str(tmp_path / "a"),
        file_pattern="{locale}.properties", key="key", value="value",
    )
    out_b = write_key_value_resources(
        frames_b, source="res", output_dir=str(tmp_path / "b"),
        file_pattern="{locale}.properties", key="key", value="value",
    )

    paths_a = list(out_a["key_value_resource_files"]["path"])
    paths_b = list(out_b["key_value_resource_files"]["path"])
    assert paths_a == paths_b


def test_output_uses_unix_line_endings(tmp_path: pytest.TempPathFactory) -> None:
    frames = {
        "resources": pd.DataFrame([
            {"key": "a", "value": "1"},
            {"key": "b", "value": "2"},
        ])
    }

    write_key_value_resources(
        frames,
        source="resources",
        output_dir=tmp_path,
        file_pattern="out.properties",
        key="key",
        value="value",
    )

    raw = (tmp_path / "out.properties").read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")
