"""Carrier-neutral final domain cleanup: command contract, producers, executor.

Contract (FTR-META-ONTOLOGY-REMOVAL-WORKBOOK-PROJECTION-EPIC-P4A, first
cleanup slice)
--------------------------------------------------------------------------

``_meta.pipeline_cleanup`` is a *command* family, not persisted history:

.. code-block:: yaml

    pipeline_cleanup:
      drop_frames: [intermediate_a, intermediate_b]

or, builder-owned keep mode:

.. code-block:: yaml

    pipeline_cleanup:
      keep_frames: [stories, characters, places]

Producers
~~~~~~~~~

* Feature transformations whose own contract establishes that a source frame
  is fully redundant contribute drop commands through
  :func:`mark_frames_for_cleanup` behind an explicit transformation parameter
  (for example ``drop_source: true`` on ``expand_xref``/``contract_xref``).
* The pipeline builder contributes commands through the
  ``configure_pipeline_cleanup`` step, because generic transformations cannot
  know whether their outputs are terminal data or disposable intermediates.

Drop mode and keep mode are alternative authoring modes for the same final
decision. A single builder declaration must use exactly one of them.
Transformation-produced drop commands compose with either builder mode:

* keep list excludes frame + drop of the same frame -> compatible, redundant;
* keep list includes frame + drop of the same frame -> conflict, fail;
* duplicate identical drop commands -> compatible, idempotent.

There is no override precedence and no ontology-derived default. The executor
never infers cleanup from generic roles, canonicality, rendering labels, or
any other broad classification.

Consumer
~~~~~~~~

:func:`execute_final_domain_cleanup` is invoked implicitly by the
orchestrator immediately after the configured pipeline steps and before the
persistence-boundary projection:

.. code-block:: text

    configured domain pipeline
    -> implicit final domain cleanup          (this module)
    -> persistence-boundary projection
    -> selected output adapter

Commands are *consumed* on execution: after the cleanup runs,
``_meta.pipeline_cleanup`` is removed so commands cannot survive into
persistable ``_meta``, roundtrip through the workbook meta blob, and
re-execute against frames a reverse pipeline later reconstructs. The
persistence boundary additionally strips the key defensively for callers
that bypass the orchestrator.

Metadata references to removed frames follow narrow per-family policies:

* explicit ``workbook_view`` mappings (``sheets[*].frame`` and
  ``sheet_mappings[*].frame``) that reference a *drop-commanded* frame are a
  conflict and fail: two targeted declarations contradict each other.
  Keep-mode *implied* removals do not conflict with view mappings -- a
  reverse pipeline legitimately reads back a workbook whose persisted
  ``workbook_view`` still maps the view frames that keep mode discards,
  and the spreadsheet renderer independently fails loudly if such a
  workbook were actually written again (missing mapped frame);
* ``sheet_mappings[*].canonical_frame`` referencing a removed frame is
  *not* a conflict -- a source frame may be legitimately removed after a
  lossless projection;
* transformation intent families (``xref_crosstable``,
  ``compact_multiaxis``, ``split_by_discriminator``, ``cell_codecs``,
  ``legend_blocks``, ``helper_policies``) are preserved unchanged: inverse
  transformations need them to recreate absent frames;
* runtime-only ``derived`` metadata keeps its existing
  persistence-boundary pruning.

Diagnostics deliberately never log frame names or frame sets; frame names
may carry domain-, business-, or person-related information with different
retention properties in logs than in data artifacts. Exceptions raised to
the caller are user-facing and follow the existing convention of naming
the offending configuration values.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

Frames = dict[str, Any]

log = logging.getLogger("sheets.cleanup")

PIPELINE_CLEANUP_KEY = "pipeline_cleanup"
DROP_FRAMES_KEY = "drop_frames"
KEEP_FRAMES_KEY = "keep_frames"

_RESERVED_FRAME_KEYS = {"_meta"}
_ALLOWED_COMMAND_KEYS = {DROP_FRAMES_KEY, KEEP_FRAMES_KEY}


# ---------------------------------------------------------------------------
# Producers
# ---------------------------------------------------------------------------


def mark_frames_for_cleanup(
    out: MutableMapping[str, Any],
    frames: Iterable[str],
) -> None:
    """Contribute transformation-produced drop commands to ``out``'s meta.

    Shared producer helper for feature transformations. Appends the given
    frame names to ``_meta.pipeline_cleanup.drop_frames`` with set-union
    semantics (duplicate identical contributions are idempotent). The caller
    owns ``out``; the helper follows the repository convention of shallow-
    copying ``_meta`` before mutation.
    """
    names = _validated_frame_names(frames, f"{PIPELINE_CLEANUP_KEY}.{DROP_FRAMES_KEY}")
    meta = dict(out.get("_meta") or {})
    commands = _command_mapping(meta.get(PIPELINE_CLEANUP_KEY))
    existing = _validated_frame_names(
        commands.get(DROP_FRAMES_KEY) or [],
        f"_meta.{PIPELINE_CLEANUP_KEY}.{DROP_FRAMES_KEY}",
        allow_empty=True,
    )
    merged = list(dict.fromkeys([*existing, *names]))
    commands[DROP_FRAMES_KEY] = merged
    meta[PIPELINE_CLEANUP_KEY] = commands
    out["_meta"] = meta


def configure_pipeline_cleanup(
    frames: Mapping[str, Any],
    *,
    drop_frames: Iterable[str] | None = None,
    keep_frames: Iterable[str] | None = None,
    name: str | None = None,
) -> Frames:
    """Builder-owned cleanup declaration step.

    Exactly one of ``drop_frames`` (name frames to remove during final domain
    cleanup) or ``keep_frames`` (name the final frame set to retain; all other
    frames are removed) must be given. The two are alternative authoring
    modes for one cleanup decision; a declaration containing both fails.

    ``drop_frames`` declarations compose across invocations and with
    transformation-produced drop commands (set union). At most one
    ``keep_frames`` declaration may exist per pipeline run.

    Frame existence is validated when the implicit final cleanup executes,
    not at declaration time, so declarations may precede the steps that
    produce the named frames.
    """
    del name
    if (drop_frames is None) == (keep_frames is None):
        raise ValueError(
            "configure_pipeline_cleanup requires exactly one of "
            "drop_frames or keep_frames; drop and keep are alternative "
            "authoring modes for one cleanup decision"
        )

    out: Frames = dict(frames)
    meta = dict(out.get("_meta") or {})
    commands = _command_mapping(meta.get(PIPELINE_CLEANUP_KEY))

    if drop_frames is not None:
        names = _validated_frame_names(drop_frames, "drop_frames")
        existing = _validated_frame_names(
            commands.get(DROP_FRAMES_KEY) or [],
            f"_meta.{PIPELINE_CLEANUP_KEY}.{DROP_FRAMES_KEY}",
            allow_empty=True,
        )
        commands[DROP_FRAMES_KEY] = list(dict.fromkeys([*existing, *names]))
    else:
        assert keep_frames is not None
        if KEEP_FRAMES_KEY in commands:
            raise ValueError(
                f"_meta.{PIPELINE_CLEANUP_KEY}.{KEEP_FRAMES_KEY} is already "
                "declared; at most one keep_frames declaration may exist per "
                "pipeline run"
            )
        commands[KEEP_FRAMES_KEY] = _validated_frame_names(keep_frames, "keep_frames")

    meta[PIPELINE_CLEANUP_KEY] = commands
    out["_meta"] = meta
    return out


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def execute_final_domain_cleanup(frames: Frames) -> Frames:
    """Execute pending cleanup commands and consume them.

    Pure function. Returns the input object unchanged when no commands are
    pending; otherwise returns a new frames dict with the resolved removal set
    dropped and ``_meta.pipeline_cleanup`` removed.

    Executes only explicit commands. Never infers cleanup from generic frame
    classifications.
    """
    meta = frames.get("_meta")
    if not isinstance(meta, Mapping) or PIPELINE_CLEANUP_KEY not in meta:
        return frames

    commands = _command_mapping(meta.get(PIPELINE_CLEANUP_KEY))
    drop_names = _validated_frame_names(
        commands.get(DROP_FRAMES_KEY) or [],
        f"_meta.{PIPELINE_CLEANUP_KEY}.{DROP_FRAMES_KEY}",
        allow_empty=True,
    )
    keep_names = (
        _validated_frame_names(
            commands[KEEP_FRAMES_KEY],
            f"_meta.{PIPELINE_CLEANUP_KEY}.{KEEP_FRAMES_KEY}",
        )
        if KEEP_FRAMES_KEY in commands
        else None
    )

    removal = _resolve_removal_set(frames, drop_names=drop_names, keep_names=keep_names)
    # Only drop-commanded frames conflict with explicit view mappings: two
    # targeted declarations contradicting each other. Keep-mode implied
    # removals coexist with (possibly reimported, stale) view mappings; the
    # spreadsheet renderer still fails loudly on missing mapped frames if
    # such a workbook is written again.
    _fail_on_workbook_view_conflicts(meta, set(drop_names) & removal)

    out: Frames = {key: value for key, value in frames.items() if key not in removal}
    new_meta = dict(meta)
    del new_meta[PIPELINE_CLEANUP_KEY]
    out["_meta"] = new_meta

    log.debug(
        "final domain cleanup: removed %d frame(s); cleanup commands consumed",
        len(removal),
    )
    return out


def _resolve_removal_set(
    frames: Mapping[str, Any],
    *,
    drop_names: list[str],
    keep_names: list[str] | None,
) -> set[str]:
    if keep_names is None:
        missing = [frame for frame in drop_names if frame not in frames]
        if missing:
            raise ValueError(
                f"_meta.{PIPELINE_CLEANUP_KEY}.{DROP_FRAMES_KEY} names "
                f"absent frame(s) {missing!r}; drop commands must target "
                "frames present at final cleanup"
            )
        return set(drop_names)

    keep_set = set(keep_names)
    conflicts = sorted(keep_set.intersection(drop_names))
    if conflicts:
        raise ValueError(
            f"Cleanup conflict: frame(s) {conflicts!r} are listed in "
            f"_meta.{PIPELINE_CLEANUP_KEY}.{KEEP_FRAMES_KEY} and also have a "
            f"{DROP_FRAMES_KEY} command; compatible declarations compose, "
            "contradictory declarations fail"
        )
    missing_keep = [frame for frame in keep_names if frame not in frames]
    if missing_keep:
        raise ValueError(
            f"_meta.{PIPELINE_CLEANUP_KEY}.{KEEP_FRAMES_KEY} names absent "
            f"frame(s) {missing_keep!r}; the retained final frame set must "
            "be present at final cleanup"
        )
    # Drop commands for frames outside the keep list are compatible and
    # redundant: keep mode already removes every frame not in the list.
    return {
        str(key)
        for key in frames
        if str(key) not in keep_set and str(key) not in _RESERVED_FRAME_KEYS
    }


def _fail_on_workbook_view_conflicts(meta: Mapping[str, Any], dropped: set[str]) -> None:
    """Fail when an explicit workbook mapping references a drop-commanded frame.

    Checks ``workbook_view.sheets[*].frame`` and
    ``workbook_view.sheet_mappings[*].frame`` against explicitly
    drop-commanded frames only; keep-mode implied removals are exempt (see
    module docstring). Legacy ``canonical_frame`` references are intentionally
    not checked: a source frame may be legitimately removed after a lossless
    projection.
    """
    if not dropped:
        return
    view = meta.get("workbook_view")
    if not isinstance(view, Mapping):
        return

    mapped: set[str] = set()
    for list_key in ("sheets", "sheet_mappings"):
        entries = view.get(list_key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, Mapping) and isinstance(entry.get("frame"), str):
                mapped.add(entry["frame"])

    conflicts = sorted(dropped.intersection(mapped))
    if conflicts:
        raise ValueError(
            f"Cleanup conflict: frame(s) {conflicts!r} are scheduled for "
            "final domain cleanup but are explicitly mapped by "
            "_meta.workbook_view; remove either the cleanup command or the "
            "workbook mapping"
        )


# ---------------------------------------------------------------------------
# Shared validation
# ---------------------------------------------------------------------------


def _command_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"_meta.{PIPELINE_CLEANUP_KEY} must be a mapping")
    unknown = sorted(set(value) - _ALLOWED_COMMAND_KEYS)
    if unknown:
        raise ValueError(
            f"_meta.{PIPELINE_CLEANUP_KEY} contains unsupported key(s) "
            f"{unknown!r}; supported keys are "
            f"{sorted(_ALLOWED_COMMAND_KEYS)!r}"
        )
    return dict(value)


def _validated_frame_names(
    values: Any,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be a list of frame names, not a scalar")
    if not isinstance(values, Iterable):
        raise TypeError(f"{field_name} must be a list of frame names")
    result = list(values)
    if not result and not allow_empty:
        raise ValueError(f"{field_name} must not be empty")
    invalid = [value for value in result if not isinstance(value, str) or not value.strip()]
    if invalid:
        raise ValueError(f"{field_name} must contain non-empty strings: {invalid!r}")
    reserved = [value for value in result if value in _RESERVED_FRAME_KEYS]
    if reserved:
        raise ValueError(f"{field_name} must not reference reserved frame(s) {reserved!r}")
    return list(dict.fromkeys(result))


__all__ = [
    "DROP_FRAMES_KEY",
    "KEEP_FRAMES_KEY",
    "PIPELINE_CLEANUP_KEY",
    "configure_pipeline_cleanup",
    "execute_final_domain_cleanup",
    "mark_frames_for_cleanup",
]
