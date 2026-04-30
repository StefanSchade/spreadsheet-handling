from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.discriminator_split import (
    merge_by_discriminator,
    split_by_discriminator,
)

pytestmark = pytest.mark.ftr("FTR-SPLIT-BY-DISCRIMINATOR-P4A")


def test_split_by_discriminator_creates_per_value_frames_and_metadata() -> None:
    frames = {
        "subject_labels": pd.DataFrame(
            [
                {"subject": "sub_1", "label": "Eingang", "sprache": "de"},
                {"subject": "sub_1", "label": "entrance", "sprache": "en"},
                {"subject": "sub_2", "label": "Ausgang", "sprache": "de"},
            ]
        )
    }

    out = split_by_discriminator(
        frames,
        source_frame="subject_labels",
        discriminator_column="sprache",
        target_pattern="subject_labels_{value}",
    )

    assert out["subject_labels_de"].to_dict(orient="records") == [
        {"subject": "sub_1", "label": "Eingang"},
        {"subject": "sub_2", "label": "Ausgang"},
    ]
    assert out["subject_labels_en"].to_dict(orient="records") == [
        {"subject": "sub_1", "label": "entrance"},
    ]
    assert out["_meta"]["split_by_discriminator"]["subject_labels"]["values"] == [
        {"value": "de", "frame": "subject_labels_de"},
        {"value": "en", "frame": "subject_labels_en"},
    ]
    assert out["_meta"]["split_by_discriminator"]["subject_labels"]["column_order"] == [
        "subject",
        "label",
        "sprache",
    ]


def test_split_merge_roundtrip_preserves_original_row_order_with_metadata() -> None:
    source = pd.DataFrame(
        [
            {"subject": "sub_1", "label": "Eingang", "sprache": "de"},
            {"subject": "sub_1", "label": "entrance", "sprache": "en"},
            {"subject": "sub_2", "label": "Ausgang", "sprache": "de"},
        ]
    )
    frames = {"subject_labels": source}

    split = split_by_discriminator(
        frames,
        source_frame="subject_labels",
        discriminator_column="sprache",
        target_pattern="subject_labels_{value}",
    )
    merged = merge_by_discriminator(
        split,
        target_frame="subject_labels",
        discriminator_column="sprache",
        source_pattern="subject_labels_{value}",
    )

    pd.testing.assert_frame_equal(merged["subject_labels"], source)


def test_merge_without_metadata_uses_pattern_bounded_sorted_sources() -> None:
    frames = {
        "subject_labels_en": pd.DataFrame([{"subject": "sub_1", "label": "entrance"}]),
        "subject_labels_de": pd.DataFrame([{"subject": "sub_1", "label": "Eingang"}]),
    }

    out = merge_by_discriminator(
        frames,
        target_frame="subject_labels",
        discriminator_column="sprache",
        source_pattern="subject_labels_{value}",
    )

    assert out["subject_labels"].to_dict(orient="records") == [
        {"subject": "sub_1", "label": "Eingang", "sprache": "de"},
        {"subject": "sub_1", "label": "entrance", "sprache": "en"},
    ]


def test_split_by_discriminator_supports_explicit_value_map() -> None:
    frames = {
        "subject_labels": pd.DataFrame(
            [
                {"subject": "sub_1", "label": "Eingang", "sprache": "de"},
                {"subject": "sub_1", "label": "entrance", "sprache": "en"},
            ]
        )
    }

    out = split_by_discriminator(
        frames,
        source_frame="subject_labels",
        discriminator_column="sprache",
        target_pattern="subject_labels_{value}",
        value_map={"de": "subject_labels_deutsch", "en": "subject_labels_english"},
    )

    assert "subject_labels_deutsch" in out
    assert "subject_labels_english" in out


def test_split_by_discriminator_rejects_duplicate_target_names() -> None:
    frames = {
        "subject_labels": pd.DataFrame(
            [
                {"subject": "sub_1", "label": "Eingang", "sprache": "de"},
                {"subject": "sub_1", "label": "entrance", "sprache": "en"},
            ]
        )
    }

    with pytest.raises(ValueError, match="Duplicate generated frame"):
        split_by_discriminator(
            frames,
            source_frame="subject_labels",
            discriminator_column="sprache",
            target_pattern="subject_labels_{value}",
            value_map={"de": "subject_labels", "en": "subject_labels"},
        )


def test_split_by_discriminator_rejects_existing_target_frame_collision() -> None:
    frames = {
        "subject_labels": pd.DataFrame([{"subject": "sub_1", "label": "Eingang", "sprache": "de"}]),
        "subject_labels_de": pd.DataFrame([{"subject": "old"}]),
    }

    with pytest.raises(ValueError, match="already exist"):
        split_by_discriminator(
            frames,
            source_frame="subject_labels",
            discriminator_column="sprache",
            target_pattern="subject_labels_{value}",
        )


def test_split_by_discriminator_rejects_non_invertible_pattern() -> None:
    frames = {
        "subject_labels": pd.DataFrame([{"subject": "sub_1", "label": "Eingang", "sprache": "de"}])
    }

    with pytest.raises(ValueError, match="exactly one"):
        split_by_discriminator(
            frames,
            source_frame="subject_labels",
            discriminator_column="sprache",
            target_pattern="subject_labels",
        )


def test_split_by_discriminator_requires_value_map_for_unsafe_values() -> None:
    frames = {
        "subject_labels": pd.DataFrame(
            [{"subject": "sub_1", "label": "Eingang", "sprache": "de/AT"}]
        )
    }

    with pytest.raises(ValueError, match="provide value_map"):
        split_by_discriminator(
            frames,
            source_frame="subject_labels",
            discriminator_column="sprache",
            target_pattern="subject_labels_{value}",
        )


def test_merge_by_discriminator_rejects_non_uniform_columns() -> None:
    frames = {
        "subject_labels_de": pd.DataFrame([{"subject": "sub_1", "label": "Eingang"}]),
        "subject_labels_en": pd.DataFrame([{"subject": "sub_1", "text": "entrance"}]),
    }

    with pytest.raises(ValueError, match="non-uniform columns"):
        merge_by_discriminator(
            frames,
            target_frame="subject_labels",
            discriminator_column="sprache",
            source_pattern="subject_labels_{value}",
        )


def test_merge_by_discriminator_rejects_source_with_discriminator_column() -> None:
    frames = {
        "subject_labels_de": pd.DataFrame(
            [{"subject": "sub_1", "label": "Eingang", "sprache": "de"}]
        ),
    }

    with pytest.raises(ValueError, match="already contains discriminator"):
        merge_by_discriminator(
            frames,
            target_frame="subject_labels",
            discriminator_column="sprache",
            source_pattern="subject_labels_{value}",
        )
