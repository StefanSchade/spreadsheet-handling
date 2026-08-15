"""Focused contract tests for Trusted Ingress Phase-E slice E3.

Covers the accepted bounded metadata substrate grammar
(`FTR-TRUSTED-INGRESS-P4A` section 11, corrected/finalized by
`FTR-TRUSTED-INGRESS-P4A_E3_metadata_census.adoc` sections 17.4/18.9/19.10/
20.7): exact ``dict``/``list`` containers, exact ``str`` keys, E1-admitted
Scalar leaves, path-active cycle rejection with acyclic-alias admission, safe
positional diagnostics, delegate-output post-check, and non-mutating
atomicity. Family semantics (Legend Blocks entry validity, XRef business
rules, ...) are deliberately out of scope here -- see their own suites.
"""

from __future__ import annotations

import copy
import datetime

import pandas as pd
import pytest

from spreadsheet_handling.domain.ingress import INGRESS_RULES, run_domain_ingress
from spreadsheet_handling.domain.ingress.metadata_admission import (
    MetadataSubstrateAdmissionError,
    admit_metadata_substrate,
)

pytestmark = pytest.mark.ftr("FTR-TRUSTED-INGRESS-P4A")


class _DictSubclass(dict):
    pass


class _ListSubclass(list):
    pass


class _OpaqueCustomObject:
    """An ordinary object with no special methods -- just not a Scalar."""


class _HostileLeafBomb:
    """A metadata leaf whose special methods must never be invoked."""

    def __repr__(self) -> str:  # pragma: no cover - must never run
        raise AssertionError("repr must not run")

    def __str__(self) -> str:  # pragma: no cover - must never run
        raise AssertionError("str must not run")

    def __eq__(self, other: object) -> bool:  # pragma: no cover - must never run
        raise AssertionError("equality must not run")

    def __hash__(self) -> int:  # pragma: no cover - must never run
        raise AssertionError("hashing must not run")

    def __iter__(self):  # pragma: no cover - must never run
        raise AssertionError("iteration must not run")


class _HostileKeyBomb:
    """A dict key whose special methods (besides construction hashing) must
    never be invoked by the walker. ``__hash__`` is real (not hostile) so the
    fixture dict can actually be constructed; the walker rejects on
    ``type(key) is not str`` alone and must never re-hash, compare, or format
    the key.
    """

    def __hash__(self) -> int:
        return 12345

    def __eq__(self, other: object) -> bool:  # pragma: no cover - must never run
        raise AssertionError("equality must not run")

    def __repr__(self) -> str:  # pragma: no cover - must never run
        raise AssertionError("repr must not run")

    def __str__(self) -> str:  # pragma: no cover - must never run
        raise AssertionError("str must not run")


class _SpoofedDictClassProperty:
    """Data descriptor so instance ``__class__`` lookup returns ``dict``.

    ``type(obj) is dict`` must stay ``False`` for this instance -- ``type()``
    reads the C-level type slot directly and never consults ``__class__``.
    """

    def __get__(self, obj: object, owner: type | None = None) -> type:
        return dict


class _SpoofedDict:
    __class__ = _SpoofedDictClassProperty()  # type: ignore[assignment]


def _meta_of(frames: dict) -> dict:
    return frames["_meta"]


# --- positive grammar matrix ------------------------------------------------


def test_absent_meta_is_noop():
    # No top-level carrier at all (beyond the absent `_meta`) so the fixture
    # also satisfies E2 ordinary structural admission, now wired into
    # `run_domain_ingress` by Phase-E slice E5; an arbitrary opaque object
    # would (correctly) be rejected before this rule ever runs.
    frames: dict = {}
    assert run_domain_ingress(frames) is frames


def test_explicit_none_meta_is_noop():
    frames = {"_meta": None}
    assert run_domain_ingress(frames) is frames


def test_empty_dict_root_is_admitted():
    frames = {"_meta": {}}
    assert run_domain_ingress(frames) is frames


def test_nested_dict_and_list_combination_is_admitted():
    frames = {
        "_meta": {
            "a": 1,
            "b": [1, "two", {"c": [True, None]}],
            "d": {"e": {"f": []}},
        }
    }
    assert run_domain_ingress(frames) is frames


@pytest.mark.parametrize(
    "leaf",
    [
        "text",
        True,
        False,
        1,
        1.5,
        None,
        "",
        float("nan"),
        datetime.date(2024, 1, 1),
        datetime.datetime(2024, 1, 1, 12, 30),
    ],
)
def test_every_e1_admitted_scalar_category_is_admitted_as_a_leaf(leaf):
    frames = {"_meta": {"value": leaf}}
    assert run_domain_ingress(frames) is frames


def test_shared_acyclic_alias_is_admitted_without_rejection():
    shared = {"style": "bold"}
    frames = {"_meta": {"a": shared, "b": shared, "c": [shared, shared]}}
    out = run_domain_ingress(frames)
    assert out is frames
    assert out["_meta"]["a"] is out["_meta"]["b"]


# --- negative grammar matrix: root ------------------------------------------


@pytest.mark.parametrize("bad_root", ["x", 5, 3.0, [1, 2], (1, 2)])
def test_non_dict_root_is_rejected(bad_root):
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": bad_root})
    assert excinfo.value.kind == "invalid_metadata_root"
    assert excinfo.value.metadata_path == "_meta"


def test_dict_subclass_root_is_rejected():
    root = _DictSubclass()
    root["other_root"] = 1  # avoid legend_blocks_shape's own dict(...) rebuild
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": root})
    assert excinfo.value.kind == "invalid_metadata_root"


# --- negative grammar matrix: nested containers/leaves ----------------------


@pytest.mark.parametrize(
    "bad_value",
    [
        _ListSubclass([1, 2]),
        (1, 2),
        {1, 2},
        b"bytes",
        complex(1, 2),
        _OpaqueCustomObject(),
    ],
    ids=["list_subclass", "tuple", "set", "bytes", "complex", "opaque_object"],
)
def test_unsupported_nested_node_is_rejected(bad_value):
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": {"a": {"b": bad_value}}})
    assert excinfo.value.kind == "invalid_metadata_node"
    assert excinfo.value.metadata_path == "_meta.a.b"


@pytest.mark.parametrize("bad_key", [1, True, 1.5, None])
def test_carrier_origin_non_str_key_is_rejected_without_coercion(bad_key):
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": {bad_key: "x"}})
    assert excinfo.value.kind == "unsupported_metadata_key"
    assert excinfo.value.metadata_path == "_meta[<entry 0>]"


def test_hashable_custom_object_key_is_rejected():
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": {_HostileKeyBomb(): "x"}})
    assert excinfo.value.kind == "unsupported_metadata_key"


def test_self_cycle_is_rejected():
    node: dict = {}
    node["self"] = node
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": node})
    assert excinfo.value.kind == "metadata_cycle_detected"
    assert excinfo.value.metadata_path == "_meta.self"


def test_indirect_ancestor_cycle_is_rejected():
    a: dict = {}
    b: dict = {}
    a["b"] = b
    b["a"] = a
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": a})
    assert excinfo.value.kind == "metadata_cycle_detected"
    assert excinfo.value.metadata_path == "_meta.b.a"


# --- path / diagnostic formatting -------------------------------------------


def test_nested_list_and_dict_path_is_rendered_structurally():
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": {"foo": [1, 2, {"bar": (1, 2)}]}})
    assert excinfo.value.metadata_path == "_meta.foo[2].bar"


# --- delegate output post-check (Legend Blocks) -----------------------------


def test_legend_blocks_output_with_non_str_key_cannot_escape_post_check():
    frames = {
        "_meta": {
            "legend_blocks": [
                {"name": "s", "entries": [{"token": "A"}], 1: "extra"},
            ]
        }
    }
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress(frames)
    assert excinfo.value.kind == "unsupported_metadata_key"
    assert "legend_blocks.s" in excinfo.value.metadata_path


def test_legend_blocks_output_with_invalid_nested_leaf_cannot_escape_post_check():
    frames = {
        "_meta": {
            "legend_blocks": {
                "s": {"entries": [{"token": "A", "extra": (1, 2)}]},
            }
        }
    }
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress(frames)
    assert excinfo.value.kind == "invalid_metadata_node"
    assert excinfo.value.metadata_path == "_meta.legend_blocks.s.entries[0].extra"


def test_legend_blocks_successful_normalization_reaches_e3_and_is_admitted():
    frames = {
        "_meta": {
            "legend_blocks": [
                {"name": "s", "entries": [{"token": "A"}], "resolved": {"top": 1}},
            ]
        }
    }
    out = run_domain_ingress(frames)
    blocks = out["_meta"]["legend_blocks"]
    assert set(blocks) == {"s"}
    assert "resolved" not in blocks["s"]


# --- atomicity / publication -------------------------------------------------


def test_invalid_nested_node_rejects_with_caller_meta_unchanged():
    frames = {"_meta": {"kept": {"x": 1}, "bad": (1, 2)}}
    before = copy.deepcopy(frames)
    with pytest.raises(MetadataSubstrateAdmissionError):
        run_domain_ingress(frames)
    assert frames == before


def test_invalid_key_rejects_with_caller_meta_unchanged():
    frames = {"_meta": {"kept": {"x": 1}}}
    frames["_meta"][1] = "extra"
    before = copy.deepcopy(frames)
    with pytest.raises(MetadataSubstrateAdmissionError):
        run_domain_ingress(frames)
    assert frames == before


def test_cycle_rejects_with_caller_meta_unchanged_by_identity():
    kept = {"x": 1}
    node: dict = {"kept": kept}
    node["self"] = node
    frames = {"_meta": node}
    with pytest.raises(MetadataSubstrateAdmissionError):
        run_domain_ingress(frames)
    # Cyclic structures cannot be compared with plain ``==``; assert identity
    # of the unrelated retained branch instead.
    assert frames["_meta"] is node
    assert frames["_meta"]["kept"] is kept
    assert frames["_meta"]["self"] is node


def test_delegate_failure_rejects_with_caller_meta_unchanged():
    frames = {"_meta": {"legend_blocks": [{"name": "dup"}, {"name": "dup"}]}}
    before = copy.deepcopy(frames)
    with pytest.raises(ValueError, match="duplicate legend block identity"):
        run_domain_ingress(frames)
    assert frames == before


def test_delegate_output_post_check_failure_rejects_with_caller_meta_unchanged():
    frames = {
        "_meta": {
            "legend_blocks": {"s": {"entries": [{"token": "A", "extra": {1, 2}}]}},
            "sheets": {"Data": {"freeze_header": True}},
        }
    }
    before = copy.deepcopy(frames)
    with pytest.raises(MetadataSubstrateAdmissionError):
        run_domain_ingress(frames)
    assert frames == before


def test_successful_delegate_normalization_does_not_touch_unrelated_branches():
    sheets = {"Data": {"freeze_header": True}}
    frames = {
        "_meta": {
            "legend_blocks": [{"name": "s", "entries": [{"token": "A"}]}],
            "sheets": sheets,
        }
    }
    out = run_domain_ingress(frames)
    assert out["_meta"]["sheets"] is sheets


# --- adversarial safety ------------------------------------------------------


def test_hostile_leaf_special_methods_are_never_invoked():
    bomb = _HostileLeafBomb()
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": {"a": bomb}})
    assert excinfo.value.kind == "invalid_metadata_node"


def test_hostile_key_special_methods_are_never_invoked_beyond_construction_hash():
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": {_HostileKeyBomb(): 1}})
    assert excinfo.value.kind == "unsupported_metadata_key"


def test_spoofed_class_property_container_is_rejected_by_exact_type():
    spoofed = _SpoofedDict()
    assert type(spoofed) is not dict  # sanity: the spoof is on __class__, not type()
    with pytest.raises(MetadataSubstrateAdmissionError) as excinfo:
        run_domain_ingress({"_meta": {"a": spoofed}})
    assert excinfo.value.kind == "invalid_metadata_node"


# --- coordinator wiring -------------------------------------------------------


def test_metadata_substrate_rule_runs_after_legend_blocks_shape():
    names = [rule.name for rule in INGRESS_RULES]
    assert names.index("metadata_substrate") > names.index("legend_blocks_shape")


def test_admit_metadata_substrate_is_directly_importable_and_matches_coordinator():
    frames = {"_meta": {"a": 1}}
    assert admit_metadata_substrate(frames) is frames


# --- XRef compatibility (no XRef-specific E3 exception) ----------------------


def test_xref_dense_axes_metadata_passes_the_generic_post_check():
    from spreadsheet_handling.domain.transformations.xref_crosstable import contract_xref

    frames = {
        "resources": pd.DataFrame({"resource_key": ["r1", "r2"]}),
        "contexts": pd.DataFrame({"context_id": ["default", "product_a"]}),
        "values": pd.DataFrame(
            [{"resource_key": "r1", "context_id": "default", "text": "Hello"}]
        ),
    }
    out = contract_xref(
        frames,
        relation="values",
        output="matrix",
        row_keys=["resource_key"],
        column_key="context_id",
        value="text",
        dense_axes={
            "rows_from": {"frame": "resources", "key": "resource_key"},
            "columns_from": {"frame": "contexts", "key": "context_id"},
        },
        name="resource_contexts",
    )

    result = run_domain_ingress(out)
    assert result["_meta"] == out["_meta"]
