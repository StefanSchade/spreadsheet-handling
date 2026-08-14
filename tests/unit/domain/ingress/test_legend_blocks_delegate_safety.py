"""Legend Blocks delegate safety: classify-before-inspect and no laundering.

Regression coverage for the independent E3 implementation review findings
`TRUSTED-INGRESS-E3-IMPL-REVIEW-F1` (unsafe pre-E3 Legend delegate
inspection) and `-F2` (unauthorized common-substrate laundering), reviewed
at `13eb8a84dabbaddd8630d1c55bfb289578ddd73b`.

F1: the pre-correction delegate performed candidate-controlled equality,
truthiness, `str()`, Mapping-protocol, and metaclass-attribute operations on
an unclassified/rejected value before the generic ``metadata_substrate``
post-check ever ran. Every test below drives the *full coordinator*
(``run_domain_ingress``), not a private helper, and proves zero such
protocol calls occur once fixture construction (which may itself legitimately
need `__hash__` for dict insertion) has completed.

F2: the pre-correction delegate reconstructed any ``Mapping``/``dict``/
``list`` subclass it touched into an exact built-in via `dict(...)`/
iteration, which silently admitted an otherwise globally invalid container
merely because a ``legend_blocks`` member was present. Every test below
proves the corrected delegate leaves such a container untouched, so the
same generic ``metadata_substrate`` rejection applies with or without the
named subtree.

Residual F1 (bounded follow-up review `6a6e8375e2a449700dc9c5a53e59916ffb3770a5`):
the first correction's `_safe_find_str_key` made every *lookup* safe, but
three staging/reconstruction sites still re-hashed or re-compared a rejected
key merely by copying it into a *different* dict object -- the root
`new_meta[_ROOT_KEY] = ...` assignment (candidate `__eq__` during native
collision resolution), `_strip_resolved`'s dict comprehension (candidate
`__hash__` on re-insertion), and `_normalize_mapping`'s
`normalized[name] = ...` (candidate `__hash__` on re-insertion). The tests in
the dedicated section below arm the hostile hook only *after* fixture
construction (which may itself legitimately need one safe `__hash__` call)
and prove each staging site now preflights every relevant dict's keys as
exact `str` before attempting any reconstruction, bailing out to the
unmodified generic post-check instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from spreadsheet_handling.domain.ingress import run_domain_ingress
from spreadsheet_handling.domain.ingress.metadata_admission import (
    MetadataSubstrateAdmissionError,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


# ---------------------------------------------------------------------------
# F1: classify-before-inspect, full coordinator
# ---------------------------------------------------------------------------


def test_colliding_hostile_root_key_triggers_zero_eq_calls():
    calls: list[Any] = []

    class HostileKey:
        """Hash collides with hash("legend_blocks"); eq raises if reached."""

        def __hash__(self) -> int:
            return hash("legend_blocks")

        def __eq__(self, other: object) -> bool:  # pragma: no cover - must never run
            calls.append(("eq", other))
            raise RuntimeError("hostile eq must not run")

    key = HostileKey()
    frames = {"_meta": {key: "x"}}
    calls.clear()  # only fixture-construction hashing may have run above

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress(frames)

    assert excinfo.value.kind == "unsupported_metadata_key"
    assert calls == []


def test_hostile_list_form_name_triggers_zero_bool_or_str_calls():
    bool_calls: list[str] = []
    str_calls: list[str] = []

    class HostileName:
        def __bool__(self) -> bool:  # pragma: no cover - must never run
            bool_calls.append("bool")
            raise RuntimeError("hostile bool must not run")

        def __str__(self) -> str:  # pragma: no cover - must never run
            str_calls.append("str")
            raise RuntimeError("hostile str must not run")

    frames = {"_meta": {"legend_blocks": [{"name": HostileName(), "entries": []}]}}
    bool_calls.clear()
    str_calls.clear()

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress(frames)

    # The identity falls back to positional; the hostile name value itself is
    # then rejected by the generic post-check as an ordinary invalid leaf.
    assert excinfo.value.kind == "invalid_metadata_node"
    assert excinfo.value.metadata_path == "_meta.legend_blocks.legend_1.name"
    assert bool_calls == []
    assert str_calls == []


def test_hostile_metaclass_root_triggers_zero_metaclass_attribute_reads():
    meta_calls: list[str] = []

    class HostileMeta(type):
        def __getattribute__(cls, name: str) -> Any:
            if name == "__name__":  # pragma: no cover - must never run
                meta_calls.append("getattr___name__")
                raise RuntimeError("hostile metaclass __name__ must not run")
            return type.__getattribute__(cls, name)

    class HostileRoot(metaclass=HostileMeta):
        pass

    frames = {"_meta": {"legend_blocks": HostileRoot()}}
    meta_calls.clear()

    with pytest.raises(ValueError, match="must be a mapping or a list"):
        run_domain_ingress(frames)

    assert meta_calls == []


def test_hostile_non_str_block_key_triggers_zero_eq_calls_against_resolved():
    eq_calls: list[Any] = []

    class HostileBlockKey:
        def __hash__(self) -> int:
            return 999

        def __eq__(self, other: object) -> bool:  # pragma: no cover - must never run
            eq_calls.append(other)
            raise RuntimeError("hostile eq must not run")

    key = HostileBlockKey()
    frames = {"_meta": {"legend_blocks": {"s": {key: "v", "entries": []}}}}
    eq_calls.clear()

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress(frames)

    assert excinfo.value.kind == "unsupported_metadata_key"
    assert eq_calls == []


def test_custom_mapping_legend_root_triggers_zero_mapping_protocol_calls():
    proto_calls: list[Any] = []

    class CustomMapping(Mapping):
        def __init__(self, data: dict) -> None:
            self._data = data

        def __getitem__(self, key: str) -> Any:  # pragma: no cover - must never run
            proto_calls.append(("getitem", key))
            return self._data[key]

        def __iter__(self):  # pragma: no cover - must never run
            proto_calls.append("iter")
            return iter(self._data)

        def __len__(self) -> int:  # pragma: no cover - must never run
            proto_calls.append("len")
            return len(self._data)

    frames = {"_meta": {"legend_blocks": CustomMapping({"s": {"entries": []}})}}
    proto_calls.clear()

    with pytest.raises(ValueError, match="must be a mapping or a list"):
        run_domain_ingress(frames)

    assert proto_calls == []


# ---------------------------------------------------------------------------
# Residual F1: staging/reconstruction must not re-hash or re-compare a
# rejected key merely by copying it into a different dict object.
# ---------------------------------------------------------------------------


def test_root_sibling_collision_with_active_legend_member_triggers_zero_eq_calls():
    # Unlike test_colliding_hostile_root_key_triggers_zero_eq_calls above,
    # this root ALSO carries a legitimate "legend_blocks" member, which
    # activates the delegate's staging/reconstruction path (`dict(meta)`
    # followed by `new_meta[_ROOT_KEY] = ...`) -- the specific site the
    # first correction's `_safe_find_str_key` did not cover.
    calls: list[Any] = []

    class HostileKey:
        def __init__(self) -> None:
            self._armed = False

        def __hash__(self) -> int:
            return hash("legend_blocks")

        def __eq__(self, other: object) -> bool:
            if self._armed:  # pragma: no cover - must never run
                calls.append(("eq", other))
                raise RuntimeError("hostile eq must not run")
            return False

    key = HostileKey()
    frames = {"_meta": {key: "x", "legend_blocks": {"s": {"entries": []}}}}
    key._armed = True  # arm only after fixture construction
    calls.clear()

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress(frames)

    assert excinfo.value.kind == "unsupported_metadata_key"
    assert calls == []


def test_list_form_block_extra_key_triggers_zero_ingress_time_hash_calls():
    hash_calls: list[str] = []

    class HostileBlockKey:
        def __init__(self) -> None:
            self._armed = False

        def __hash__(self) -> int:
            if self._armed:  # pragma: no cover - must never run
                hash_calls.append("hash")
                raise RuntimeError("hostile hash must not run")
            return 12345

        def __eq__(self, other: object) -> bool:
            return False

    key = HostileBlockKey()
    item = {"name": "s", "entries": [], key: "extra"}
    frames = {"_meta": {"legend_blocks": [item]}}
    key._armed = True  # arm only after fixture construction
    hash_calls.clear()

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress(frames)

    assert excinfo.value.kind == "unsupported_metadata_key"
    assert hash_calls == []


def test_mapping_form_outer_key_triggers_zero_ingress_time_hash_calls():
    hash_calls: list[str] = []

    class HostileOuterKey:
        def __init__(self) -> None:
            self._armed = False

        def __hash__(self) -> int:
            if self._armed:  # pragma: no cover - must never run
                hash_calls.append("hash")
                raise RuntimeError("hostile hash must not run")
            return 54321

        def __eq__(self, other: object) -> bool:
            return False

    key = HostileOuterKey()
    frames = {"_meta": {"legend_blocks": {key: {"entries": []}}}}
    key._armed = True  # arm only after fixture construction
    hash_calls.clear()

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress(frames)

    assert excinfo.value.kind == "unsupported_metadata_key"
    assert hash_calls == []


def test_safe_staging_still_normalizes_when_every_key_is_admitted():
    # Positive companion: the new preflights must not block ordinary staging
    # when every relevant key really is an exact str.
    sheets = {"Data": {"freeze_header": True}}
    shared_entries = [{"token": "A"}]
    frames = {
        "_meta": {
            "sheets": sheets,
            "legend_blocks": [
                {"name": "s", "entries": shared_entries, "resolved": {"top": 1}},
            ],
        }
    }

    out = run_domain_ingress(frames)

    blocks = out["_meta"]["legend_blocks"]
    assert set(blocks) == {"s"}
    assert "resolved" not in blocks["s"]
    assert blocks["s"]["entries"] is shared_entries
    assert out["_meta"]["sheets"] is sheets


# ---------------------------------------------------------------------------
# F2: no laundering into the common substrate
# ---------------------------------------------------------------------------


class _DictSubclass(dict):
    pass


class _ListSubclass(list):
    pass


class _CustomMappingRoot(Mapping):
    def __init__(self, data: dict) -> None:
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def test_meta_dict_subclass_with_legend_blocks_is_rejected():
    meta = _DictSubclass()
    meta["legend_blocks"] = None
    meta["ok"] = 1

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": meta})
    assert excinfo.value.kind == "invalid_metadata_root"


def test_meta_dict_subclass_without_legend_blocks_is_rejected_identically():
    # Control case: presence/absence of legend_blocks must not change the
    # global-root verdict.
    meta = _DictSubclass()
    meta["ok"] = 1

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": meta})
    assert excinfo.value.kind == "invalid_metadata_root"


def test_meta_custom_mapping_with_legend_blocks_is_rejected():
    meta = _CustomMappingRoot({"legend_blocks": None, "ok": 1})

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": meta})
    assert excinfo.value.kind == "invalid_metadata_root"


def test_meta_custom_mapping_without_legend_blocks_is_rejected_identically():
    meta = _CustomMappingRoot({"ok": 1})

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": meta})
    assert excinfo.value.kind == "invalid_metadata_root"


def test_legend_blocks_dict_subclass_is_rejected():
    root = _DictSubclass()
    root["s"] = {"entries": []}

    with pytest.raises(ValueError, match="must be a mapping or a list"):
        run_domain_ingress({"_meta": {"legend_blocks": root}})


def test_legend_blocks_custom_mapping_is_rejected():
    root = _CustomMappingRoot({"s": {"entries": []}})

    with pytest.raises(ValueError, match="must be a mapping or a list"):
        run_domain_ingress({"_meta": {"legend_blocks": root}})


def test_legend_blocks_list_subclass_is_rejected():
    root = _ListSubclass([{"name": "s", "entries": []}])

    with pytest.raises(ValueError, match="must be a mapping or a list"):
        run_domain_ingress({"_meta": {"legend_blocks": root}})


def test_legend_block_dict_subclass_is_rejected():
    block = _DictSubclass()
    block["entries"] = []

    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": {"legend_blocks": {"s": block}}})
    assert excinfo.value.kind == "invalid_metadata_node"
    assert excinfo.value.metadata_path == "_meta.legend_blocks.s"


# ---------------------------------------------------------------------------
# Valid authoring behavior preserved (sanity companions to the dedicated
# shape-normalization suite in test_legend_blocks_ingress.py)
# ---------------------------------------------------------------------------


def test_valid_mapping_and_list_forms_are_still_admitted():
    mapping_out = run_domain_ingress(
        {"_meta": {"legend_blocks": {"s": {"entries": [{"token": "A"}]}}}}
    )
    assert mapping_out["_meta"]["legend_blocks"] == {"s": {"entries": [{"token": "A"}]}}

    list_out = run_domain_ingress(
        {
            "_meta": {
                "legend_blocks": [
                    {"name": "s", "entries": [{"token": "A"}], "resolved": {"top": 1}},
                ]
            }
        }
    )
    blocks = list_out["_meta"]["legend_blocks"]
    assert set(blocks) == {"s"}
    assert "resolved" not in blocks["s"]


def test_name_present_but_non_str_falls_back_to_id_then_position_safely():
    # A non-str "name" is safely skipped for identity resolution (never
    # given truthiness/str), falling through to "id"; the still-present
    # non-str "name" *value* is then independently rejected by the generic
    # post-check like any other out-of-grammar leaf.
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress(
            {"_meta": {"legend_blocks": [{"name": (1, 2), "id": "i", "entries": []}]}}
        )
    assert excinfo.value.kind == "invalid_metadata_node"
    assert excinfo.value.metadata_path == "_meta.legend_blocks.i.name"
