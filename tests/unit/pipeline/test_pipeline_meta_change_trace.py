"""Protect DEBUG gating and failure isolation at the central pipeline boundary."""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from spreadsheet_handling.pipeline import BoundStep, run_pipeline
from spreadsheet_handling.pipeline import execution

pytestmark = pytest.mark.ftr("FTR-PIPELINE-META-CHANGE-TRACE-P5")


def _frames() -> dict[str, object]:
    return {"places": pd.DataFrame({"id": ["P-1"]})}


def test_disabled_debug_path_performs_no_snapshot_or_diff_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("diagnostic helper must not run")

    monkeypatch.setattr(execution.log, "isEnabledFor", lambda level: False)
    monkeypatch.setattr(execution, "snapshot_meta", forbidden)
    monkeypatch.setattr(execution, "diff_meta", forbidden)
    monkeypatch.setattr(execution, "format_meta_diff", forbidden)
    frames = _frames()
    step = BoundStep(name="identity", config={}, fn=lambda current: current)

    result = run_pipeline(frames, [step])

    assert result is frames


def test_enabled_debug_observes_each_successful_step_and_emits_distinct_summaries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    frames = _frames()

    def add_policy(current: dict[str, object]) -> dict[str, object]:
        current["_meta"] = {"policy": {"mode": "initial"}}
        return current

    def change_policy(current: dict[str, object]) -> dict[str, object]:
        current["_meta"]["policy"]["mode"] = "strict"  # type: ignore[index]
        return current

    steps = [
        BoundStep(name="add_policy", config={}, fn=add_policy),
        BoundStep(name="change_policy", config={}, fn=change_policy),
        BoundStep(name="identity", config={}, fn=lambda current: current),
    ]

    with caplog.at_level(logging.DEBUG, logger="sheets.pipeline"):
        result = run_pipeline(frames, steps)

    summaries = [record.getMessage() for record in caplog.records if record.getMessage().startswith("<-")]
    assert result is frames
    assert len(summaries) == 3
    assert "<- step: add_policy" in summaries[0]
    assert "policy" in summaries[0]
    assert "<- step: change_policy" in summaries[1]
    assert "policy.mode" in summaries[1]
    assert summaries[2] == "<- step: identity\nmeta: unchanged"


def test_enabled_debug_snapshots_before_and_after_every_successful_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    real_snapshot = execution.snapshot_meta

    def counting_snapshot(frames: dict[str, object]):
        nonlocal calls
        calls += 1
        return real_snapshot(frames)

    monkeypatch.setattr(execution.log, "isEnabledFor", lambda level: True)
    monkeypatch.setattr(execution, "snapshot_meta", counting_snapshot)
    steps = [
        BoundStep(name="first", config={}, fn=lambda current: current),
        BoundStep(name="second", config={}, fn=lambda current: current),
    ]

    run_pipeline(_frames(), steps)

    assert calls == 4


def test_before_snapshot_failure_does_not_prevent_valid_step(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(execution.log, "isEnabledFor", lambda level: True)
    monkeypatch.setattr(execution, "snapshot_meta", lambda frames: (_ for _ in ()).throw(RuntimeError()))
    frames = _frames()
    step = BoundStep(name="valid", config={}, fn=lambda current: current)

    with caplog.at_level(logging.DEBUG, logger="sheets.pipeline"):
        result = run_pipeline(frames, [step])

    assert result is frames
    assert "<- step: valid\nmeta: diagnostic limited" in caplog.messages


@pytest.mark.parametrize("failing_stage", ["after_snapshot", "diff", "format"])
def test_after_step_diagnostic_failure_does_not_alter_valid_result(
    failing_stage: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(execution.log, "isEnabledFor", lambda level: True)
    if failing_stage == "after_snapshot":
        real_snapshot = execution.snapshot_meta
        calls = 0

        def fail_second_snapshot(frames: dict[str, object]):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("after snapshot failed")
            return real_snapshot(frames)

        monkeypatch.setattr(execution, "snapshot_meta", fail_second_snapshot)
    elif failing_stage == "diff":
        monkeypatch.setattr(execution, "diff_meta", lambda before, after: (_ for _ in ()).throw(RuntimeError()))
    else:
        monkeypatch.setattr(execution, "format_meta_diff", lambda name, diff: (_ for _ in ()).throw(RuntimeError()))

    frames = _frames()

    def valid_step(current: dict[str, object]) -> dict[str, object]:
        current["_meta"] = {"policy": {"enabled": True}}
        return current

    with caplog.at_level(logging.DEBUG, logger="sheets.pipeline"):
        result = run_pipeline(frames, [BoundStep(name="valid", config={}, fn=valid_step)])

    assert result is frames
    assert result["_meta"] == {"policy": {"enabled": True}}
    assert "<- step: valid\nmeta: diagnostic limited" in caplog.messages


def test_step_exception_propagates_unchanged_without_after_summary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure = RuntimeError("step failed")

    def fail(current: dict[str, object]) -> dict[str, object]:
        raise failure

    with caplog.at_level(logging.DEBUG, logger="sheets.pipeline"):
        with pytest.raises(RuntimeError) as caught:
            run_pipeline(_frames(), [BoundStep(name="failing", config={}, fn=fail)])

    assert caught.value is failure
    assert not any(message.startswith("<-") for message in caplog.messages)


def test_existing_step_configuration_log_message_remains_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    step = BoundStep(name="identity", config={"token": "existing"}, fn=lambda current: current)

    with caplog.at_level(logging.DEBUG, logger="sheets.pipeline"):
        run_pipeline(_frames(), [step])

    assert "-> step: identity config={'token': 'existing'}" in caplog.messages
