"""Unit tests for the carrier-neutral final domain cleanup contract.

Covers the command schema, producer helpers, the builder step, executor
semantics (consumption, idempotence, conflicts), per-family metadata
policies, and the privacy constraint on cleanup diagnostics.
"""
from __future__ import annotations

import logging

import pandas as pd
import pytest

from spreadsheet_handling.domain.pipeline_cleanup import (
    DROP_FRAMES_KEY,
    PIPELINE_CLEANUP_KEY,
    configure_pipeline_cleanup,
    execute_final_domain_cleanup,
    mark_frames_for_cleanup,
)

pytestmark = pytest.mark.ftr("FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A")


def _frames(**extra: object) -> dict:
    frames: dict = {
        "stories": pd.DataFrame({"id": [1]}),
        "characters": pd.DataFrame({"id": [2]}),
        "relation_source": pd.DataFrame({"id": [3]}),
    }
    frames.update(extra)
    return frames


# ---------------------------------------------------------------------------
# Drop mode
# ---------------------------------------------------------------------------


def test_explicit_drop_command_removes_present_frame() -> None:
    frames = configure_pipeline_cleanup(_frames(), drop_frames=["relation_source"])

    cleaned = execute_final_domain_cleanup(frames)

    assert sorted(cleaned) == ["_meta", "characters", "stories"]


def test_absence_of_commands_preserves_all_frames() -> None:
    frames = _frames(_meta={"frame_lifecycle": {"stories": {"role": "whatever"}}})

    cleaned = execute_final_domain_cleanup(frames)

    assert cleaned is frames


def test_commands_are_consumed_on_execution() -> None:
    frames = configure_pipeline_cleanup(_frames(), drop_frames=["relation_source"])

    cleaned = execute_final_domain_cleanup(frames)

    assert PIPELINE_CLEANUP_KEY not in cleaned["_meta"]


def test_executor_is_idempotent_after_consumption() -> None:
    frames = configure_pipeline_cleanup(_frames(), drop_frames=["relation_source"])

    cleaned = execute_final_domain_cleanup(frames)
    again = execute_final_domain_cleanup(cleaned)

    assert again is cleaned


def test_duplicate_identical_drop_contributions_are_idempotent() -> None:
    frames = _frames(_meta={})
    mark_frames_for_cleanup(frames, ["relation_source"])
    mark_frames_for_cleanup(frames, ["relation_source"])
    frames = configure_pipeline_cleanup(frames, drop_frames=["relation_source"])

    assert frames["_meta"][PIPELINE_CLEANUP_KEY][DROP_FRAMES_KEY] == ["relation_source"]

    cleaned = execute_final_domain_cleanup(frames)

    assert "relation_source" not in cleaned


def test_drop_command_for_absent_frame_fails() -> None:
    frames = configure_pipeline_cleanup(_frames(), drop_frames=["missing_frame"])

    with pytest.raises(ValueError, match="absent frame"):
        execute_final_domain_cleanup(frames)


def test_input_frames_are_not_mutated() -> None:
    frames = configure_pipeline_cleanup(_frames(), drop_frames=["relation_source"])
    before_keys = sorted(frames)
    before_meta = dict(frames["_meta"])

    execute_final_domain_cleanup(frames)

    assert sorted(frames) == before_keys
    assert frames["_meta"] == before_meta


# ---------------------------------------------------------------------------
# Keep mode and composition
# ---------------------------------------------------------------------------


def test_keep_mode_removes_unlisted_frames() -> None:
    frames = configure_pipeline_cleanup(_frames(), keep_frames=["stories", "characters"])

    cleaned = execute_final_domain_cleanup(frames)

    assert sorted(cleaned) == ["_meta", "characters", "stories"]


def test_keep_mode_with_absent_keep_frame_fails() -> None:
    frames = configure_pipeline_cleanup(_frames(), keep_frames=["stories", "missing"])

    with pytest.raises(ValueError, match="absent frame"):
        execute_final_domain_cleanup(frames)


def test_keep_mode_plus_compatible_transformation_drop_is_redundant() -> None:
    frames = _frames(_meta={})
    mark_frames_for_cleanup(frames, ["relation_source"])
    frames = configure_pipeline_cleanup(frames, keep_frames=["stories", "characters"])

    cleaned = execute_final_domain_cleanup(frames)

    assert sorted(cleaned) == ["_meta", "characters", "stories"]


def test_keep_mode_plus_contradictory_transformation_drop_fails() -> None:
    frames = _frames(_meta={})
    mark_frames_for_cleanup(frames, ["stories"])
    frames = configure_pipeline_cleanup(
        frames, keep_frames=["stories", "characters", "relation_source"]
    )

    with pytest.raises(ValueError, match="Cleanup conflict"):
        execute_final_domain_cleanup(frames)


def test_builder_declaration_with_both_modes_fails() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        configure_pipeline_cleanup(_frames(), drop_frames=["a"], keep_frames=["b"])

    with pytest.raises(ValueError, match="exactly one"):
        configure_pipeline_cleanup(_frames())


def test_second_keep_declaration_fails() -> None:
    frames = configure_pipeline_cleanup(_frames(), keep_frames=["stories"])

    with pytest.raises(ValueError, match="already"):
        configure_pipeline_cleanup(frames, keep_frames=["characters"])


def test_builder_drop_declarations_compose_across_invocations() -> None:
    frames = configure_pipeline_cleanup(_frames(), drop_frames=["relation_source"])
    frames = configure_pipeline_cleanup(frames, drop_frames=["characters"])

    assert frames["_meta"][PIPELINE_CLEANUP_KEY][DROP_FRAMES_KEY] == [
        "relation_source",
        "characters",
    ]


# ---------------------------------------------------------------------------
# Validation failures
# ---------------------------------------------------------------------------


def test_reserved_frame_targeting_fails_in_all_producers() -> None:
    with pytest.raises(ValueError, match="reserved"):
        configure_pipeline_cleanup(_frames(), drop_frames=["_meta"])

    with pytest.raises(ValueError, match="reserved"):
        configure_pipeline_cleanup(_frames(), keep_frames=["_meta"])

    with pytest.raises(ValueError, match="reserved"):
        mark_frames_for_cleanup(_frames(_meta={}), ["_meta"])


def test_empty_and_non_string_frame_names_fail() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        configure_pipeline_cleanup(_frames(), drop_frames=[""])

    with pytest.raises(ValueError, match="must not be empty"):
        configure_pipeline_cleanup(_frames(), drop_frames=[])

    with pytest.raises(TypeError, match="not a scalar"):
        configure_pipeline_cleanup(_frames(), drop_frames="stories")


def test_malformed_pipeline_cleanup_meta_fails() -> None:
    not_mapping = _frames(_meta={PIPELINE_CLEANUP_KEY: ["stories"]})
    with pytest.raises(TypeError, match="must be a mapping"):
        execute_final_domain_cleanup(not_mapping)

    unknown_key = _frames(_meta={PIPELINE_CLEANUP_KEY: {"drop_frame": ["stories"]}})
    with pytest.raises(ValueError, match="unsupported key"):
        execute_final_domain_cleanup(unknown_key)

    scalar_list = _frames(_meta={PIPELINE_CLEANUP_KEY: {DROP_FRAMES_KEY: "stories"}})
    with pytest.raises(TypeError, match="not a scalar"):
        execute_final_domain_cleanup(scalar_list)


# ---------------------------------------------------------------------------
# Workbook View conflicts and per-family metadata policies
# ---------------------------------------------------------------------------


def test_explicit_workbook_view_sheet_mapping_of_dropped_frame_fails() -> None:
    frames = _frames(
        _meta={
            "workbook_view": {
                "sheets": [{"frame": "relation_source", "sheet": "Relations"}],
            }
        }
    )
    frames = configure_pipeline_cleanup(frames, drop_frames=["relation_source"])

    with pytest.raises(ValueError, match="explicitly mapped"):
        execute_final_domain_cleanup(frames)


def test_persisted_sheet_mapping_of_dropped_frame_fails() -> None:
    frames = _frames(
        _meta={
            "workbook_view": {
                "sheet_mappings": [{"sheet": "Relations", "frame": "relation_source"}],
            }
        }
    )
    frames = configure_pipeline_cleanup(frames, drop_frames=["relation_source"])

    with pytest.raises(ValueError, match="explicitly mapped"):
        execute_final_domain_cleanup(frames)


def test_keep_mode_implied_removal_coexists_with_reimported_view_mappings() -> None:
    # A reverse pipeline reads back a workbook whose persisted workbook_view
    # still maps view frames that keep mode discards. Those implied removals
    # are not targeted contradictions and must not fail; the renderer guards
    # any future workbook write independently.
    frames = _frames(
        _meta={
            "workbook_view": {
                "sheets": [{"frame": "relation_source", "sheet": "Relations"}],
                "sheet_mappings": [{"sheet": "Relations", "frame": "relation_source"}],
            }
        }
    )
    frames = configure_pipeline_cleanup(frames, keep_frames=["stories", "characters"])

    cleaned = execute_final_domain_cleanup(frames)

    assert sorted(cleaned) == ["_meta", "characters", "stories"]


def test_drop_command_conflicts_with_view_mapping_even_in_keep_mode() -> None:
    frames = _frames(
        _meta={
            "workbook_view": {
                "sheets": [{"frame": "relation_source", "sheet": "Relations"}],
            }
        }
    )
    mark_frames_for_cleanup(frames, ["relation_source"])
    frames = configure_pipeline_cleanup(frames, keep_frames=["stories", "characters"])

    with pytest.raises(ValueError, match="explicitly mapped"):
        execute_final_domain_cleanup(frames)


def test_canonical_frame_reference_to_dropped_frame_is_not_a_conflict() -> None:
    # A source frame may be legitimately removed after a lossless projection;
    # sheet_mappings[*].canonical_frame referencing it must not fail cleanup.
    frames = _frames(
        _meta={
            "workbook_view": {
                "sheet_mappings": [
                    {
                        "sheet": "Stories",
                        "frame": "stories",
                        "canonical_frame": "relation_source",
                    }
                ],
            }
        }
    )
    frames = configure_pipeline_cleanup(frames, drop_frames=["relation_source"])

    cleaned = execute_final_domain_cleanup(frames)

    assert "relation_source" not in cleaned
    assert cleaned["_meta"]["workbook_view"]["sheet_mappings"][0]["canonical_frame"] == (
        "relation_source"
    )


def test_frame_lifecycle_entry_of_dropped_frame_is_removed_others_kept() -> None:
    frames = _frames(
        _meta={
            "frame_lifecycle": {
                "relation_source": {"role": "anything"},
                "stories": {"role": "anything_else"},
            }
        }
    )
    frames = configure_pipeline_cleanup(frames, drop_frames=["relation_source"])

    cleaned = execute_final_domain_cleanup(frames)

    assert "relation_source" not in cleaned["_meta"]["frame_lifecycle"]
    assert "stories" in cleaned["_meta"]["frame_lifecycle"]


def test_transformation_intent_referencing_dropped_frame_is_preserved() -> None:
    # Inverse transformations need intent metadata to recreate absent frames;
    # references to a dropped frame are required intent, not contradictions.
    intent = {
        "story_matrix": {
            "operation": "contract_xref",
            "relation": "relation_source",
            "matrix": "story_matrix",
        }
    }
    frames = _frames(
        story_matrix=pd.DataFrame({"id": [4]}),
        _meta={"xref_crosstable": intent, "compact_multiaxis": {"c": {"matrix": "relation_source"}}},
    )
    frames = configure_pipeline_cleanup(frames, drop_frames=["relation_source"])

    cleaned = execute_final_domain_cleanup(frames)

    assert cleaned["_meta"]["xref_crosstable"] == intent
    assert cleaned["_meta"]["compact_multiaxis"] == {"c": {"matrix": "relation_source"}}


# ---------------------------------------------------------------------------
# Diagnostics privacy
# ---------------------------------------------------------------------------


def test_debug_diagnostics_do_not_emit_frame_names(
    caplog: pytest.LogCaptureFixture,
) -> None:
    frames = _frames(
        confidential_person_frame=pd.DataFrame({"id": [9]}),
    )
    frames = configure_pipeline_cleanup(frames, drop_frames=["confidential_person_frame"])

    with caplog.at_level(logging.DEBUG, logger="sheets.cleanup"):
        execute_final_domain_cleanup(frames)

    assert caplog.records
    for record in caplog.records:
        assert "confidential_person_frame" not in record.getMessage()
