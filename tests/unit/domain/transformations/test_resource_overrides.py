from __future__ import annotations

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.resource_overrides import (
    ResourceOverridePolicy,
    normalize_resource_override_frame,
    normalize_resource_overrides,
)


pytestmark = pytest.mark.ftr("FTR-RESOURCE-FALLBACK-OVERRIDE-SEMANTICS-P4A")


def _localized_policy(**overrides: object) -> ResourceOverridePolicy:
    values = {
        "default_context": "default",
        "default_required": True,
        "empty_override": "omit_tuple",
        "explicit_empty_marker": "<empty>",
        "collapse_override_equal_to_default": True,
    }
    values.update(overrides)
    return ResourceOverridePolicy(**values)


def _normalize(frame: pd.DataFrame, **policy_overrides: object) -> pd.DataFrame:
    result = normalize_resource_override_frame(
        frame,
        frame_name="localized_values",
        row_keys=["resource_key"],
        discriminator_column="locale",
        context_column="context_id",
        value_column="text",
        policy=_localized_policy(**policy_overrides),
    )
    assert result.findings == []
    return result.frame


def test_empty_override_is_omitted_when_policy_says_omit_tuple() -> None:
    frame = pd.DataFrame([
        {"resource_key": "greeting", "locale": "en", "context_id": "default", "text": "Hello"},
        {"resource_key": "greeting", "locale": "en", "context_id": "product_a", "text": ""},
    ])

    out = _normalize(frame)

    assert out.to_dict(orient="records") == [
        {"resource_key": "greeting", "locale": "en", "context_id": "default", "text": "Hello"},
    ]


def test_explicit_empty_marker_keeps_override_with_empty_text() -> None:
    frame = pd.DataFrame([
        {"resource_key": "greeting", "locale": "en", "context_id": "default", "text": "Hello"},
        {
            "resource_key": "greeting",
            "locale": "en",
            "context_id": "product_a",
            "text": "<empty>",
        },
    ])

    out = _normalize(frame)

    assert out.to_dict(orient="records") == [
        {"resource_key": "greeting", "locale": "en", "context_id": "default", "text": "Hello"},
        {"resource_key": "greeting", "locale": "en", "context_id": "product_a", "text": ""},
    ]


def test_override_equal_to_default_collapses_when_configured() -> None:
    frame = pd.DataFrame([
        {"resource_key": "greeting", "locale": "en", "context_id": "default", "text": "Hello"},
        {"resource_key": "greeting", "locale": "en", "context_id": "product_a", "text": "Hello"},
    ])

    out = _normalize(frame)

    assert out.to_dict(orient="records") == [
        {"resource_key": "greeting", "locale": "en", "context_id": "default", "text": "Hello"},
    ]


def test_override_equal_to_default_is_retained_when_configured() -> None:
    frame = pd.DataFrame([
        {"resource_key": "greeting", "locale": "en", "context_id": "default", "text": "Hello"},
        {"resource_key": "greeting", "locale": "en", "context_id": "product_a", "text": "Hello"},
    ])

    out = _normalize(frame, collapse_override_equal_to_default=False)

    assert out.to_dict(orient="records") == [
        {"resource_key": "greeting", "locale": "en", "context_id": "default", "text": "Hello"},
        {"resource_key": "greeting", "locale": "en", "context_id": "product_a", "text": "Hello"},
    ]


def test_required_default_missing_produces_finding_and_pipeline_failure() -> None:
    frame = pd.DataFrame([
        {"resource_key": "greeting", "locale": "en", "context_id": "product_a", "text": "Hello"},
    ])
    result = normalize_resource_override_frame(
        frame,
        frame_name="localized_values",
        row_keys=["resource_key"],
        discriminator_column="locale",
        context_column="context_id",
        value_column="text",
        policy=_localized_policy(),
    )

    assert [finding.rule_type for finding in result.findings] == ["missing_default"]
    with pytest.raises(ValueError, match="missing_default"):
        normalize_resource_overrides(
            {"localized_values": frame},
            source="localized_values",
            row_keys=["resource_key"],
            discriminator_column="locale",
            context_column="context_id",
            value_column="text",
            default_context="default",
            mode="fail",
        )


def test_empty_default_text_is_valid_when_configured() -> None:
    frame = pd.DataFrame([
        {"resource_key": "empty_label", "locale": "en", "context_id": "default", "text": ""},
    ])

    out = _normalize(frame, allow_empty_default=True)

    assert out.to_dict(orient="records") == [
        {"resource_key": "empty_label", "locale": "en", "context_id": "default", "text": ""},
    ]


def test_duplicate_conflicting_tuples_produce_clear_validation_error() -> None:
    frame = pd.DataFrame([
        {"resource_key": "greeting", "locale": "en", "context_id": "default", "text": "Hello"},
        {"resource_key": "greeting", "locale": "en", "context_id": "default", "text": "Hi"},
    ])

    with pytest.raises(ValueError, match="conflicting_tuple"):
        normalize_resource_overrides(
            {"localized_values": frame},
            source="localized_values",
            row_keys=["resource_key"],
            discriminator_column="locale",
            context_column="context_id",
            value_column="text",
            default_context="default",
            mode="fail",
        )


def test_normalizes_expanded_matrix_output_without_owning_matrix_shape() -> None:
    expanded_matrix_output = pd.DataFrame([
        {"resource_key": "greeting", "locale": "en", "context_id": "default", "text": "Hello"},
        {"resource_key": "greeting", "locale": "en", "context_id": "product_a", "text": ""},
        {"resource_key": "greeting", "locale": "en", "context_id": "product_b", "text": "Howdy"},
        {"resource_key": "greeting", "locale": "de", "context_id": "default", "text": "Hallo"},
        {"resource_key": "greeting", "locale": "de", "context_id": "product_a", "text": "Hallo"},
    ])

    out = _normalize(expanded_matrix_output)

    assert out.to_dict(orient="records") == [
        {"resource_key": "greeting", "locale": "en", "context_id": "default", "text": "Hello"},
        {"resource_key": "greeting", "locale": "en", "context_id": "product_b", "text": "Howdy"},
        {"resource_key": "greeting", "locale": "de", "context_id": "default", "text": "Hallo"},
    ]


def test_production_api_uses_configured_column_names() -> None:
    frame = pd.DataFrame([
        {"message_id": "m1", "variant": "saas", "scope": "base", "payload": "Enabled"},
        {"message_id": "m1", "variant": "saas", "scope": "enterprise", "payload": ""},
    ])
    result = normalize_resource_override_frame(
        frame,
        row_keys=["message_id"],
        discriminator_column="variant",
        context_column="scope",
        value_column="payload",
        policy=ResourceOverridePolicy(default_context="base"),
    )

    assert result.frame.to_dict(orient="records") == [
        {"message_id": "m1", "variant": "saas", "scope": "base", "payload": "Enabled"},
    ]

