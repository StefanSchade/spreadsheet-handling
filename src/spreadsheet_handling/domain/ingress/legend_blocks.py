"""Legend Blocks shape-normalization rule for the domain ingress boundary.

External authoring accepts ``_meta.legend_blocks`` as either an
insertion-ordered exact ``dict`` keyed by Legend Block identity, or an exact
``list`` of block ``dict`` mappings whose identity is resolved from
``name`` / ``id`` / positional fallback. List form is authoring sugar only:
this rule normalizes it once, at the external-to-domain ingress boundary, to
the single canonical mapping form so that no downstream domain
transformation, renderer, validation pass, persistence projector, or
framework-produced carrier ever receives list form.

The rule is a pure ``Frames -> Frames`` transformation. It never mutates the
caller's ``frames``, ``_meta``, the ``legend_blocks`` container, or any block
mapping; it validates and constructs the complete candidate result before
returning it, so a shape or duplicate-identity failure leaves the input object
graph unchanged.

Entry-value semantics (token validity, labels, duplicate entry tokens, empty
entries, unknown references, unhashable tokens) are deliberately *not* decided
here; they belong to ``FTR-LEGEND-BLOCKS-ENTRY-CONTRACT-P5``. This rule only
canonicalizes the block-container shape and drops the render-derived
``resolved`` Resolution facet (never durable Intent).

Bounded named-delegate authority (`FTR-TRUSTED-INGRESS-P4A` section 11,
"Controlled metadata delegate governance"; `TRUSTED-INGRESS-E3-IMPL-REVIEW-F1`/
`-F2` correction, with a bounded residual-F1 staging follow-up): this
delegate owns *authoring shape* for exactly the
``_meta.legend_blocks`` root, not the global metadata substrate. It is
authorized to accept the two authoring forms above -- an exact ``dict`` or an
exact ``list`` -- nothing else. A ``dict``/``list`` *subclass*, a ``Mapping``
implementation, or any other value is never coerced into a conforming
container merely because Python can traverse or reconstruct it; it is left
completely untouched (the delegate no-ops) so the generic ``metadata_substrate``
post-check rejects it uniformly with an ordinary substrate diagnostic, exactly
as it would reject the same shape anywhere else in ``_meta``. The same rule
applies one level up: the delegate only ever inspects ``_meta`` itself when
``_meta`` is already exactly ``dict``; a non-``dict`` global root is left
untouched for the generic walker, never normalized into one merely because a
``legend_blocks`` member happens to be present (that would let an unrelated,
otherwise-invalid root "launder" into the accepted substrate through this
delegate).

Safe classify-before-inspect (per the same governance section, and the
project-wide boundary-robustness discipline already established for E1/E2):
every unclassified candidate this module encounters -- a root key, a list
member, a block key, an identity field -- is classified by exact ``type()``
*before* any comparison, truthiness check, formatting, or iteration that the
candidate could control. In particular this module never performs an
ordinary hash-based dict lookup (``in``, ``.get()``, ``[]``) against a mapping
that may still contain an unclassified key, because a hostile key whose
``__hash__`` happens to collide with a literal being searched for (e.g.
``"legend_blocks"``) can otherwise have its ``__eq__`` invoked by the dict
implementation itself before this module ever gets to classify it; see
``_safe_find_str_key``. Rejection diagnostics never derive a dynamic runtime
type name (``type(x).__name__``), because a hostile metaclass can intercept
that attribute read; they name only the stable failure shape and (where
applicable) a safe positional location, matching the diagnostic discipline
already established by ``core.scalar_values`` and
``domain.ingress.structural_admission``.

Safe lookup is not sufficient by itself: every place this module *stages* a
new dict from an already-admitted one (copying an exact ``_meta``/
``legend_blocks``/block ``dict`` and inserting into it, or comprehending one
into a fresh dict) re-hashes or re-compares whichever of its own keys
participate in that reconstruction, even a key that was found perfectly
safely a moment earlier. See ``_all_keys_are_exact_str``, run as a preflight
before every such reconstruction.
"""

from __future__ import annotations

from typing import Any

Frames = dict[str, Any]

_ROOT_KEY = "legend_blocks"
_NAME_KEY = "name"
_ID_KEY = "id"
_RESOLVED_KEY = "resolved"


def _all_keys_are_exact_str(mapping: dict[Any, Any]) -> bool:
    """Whether every key of an already-confirmed exact ``dict`` is exact ``str``.

    Only ever evaluates ``type(key) is str`` -- never hashes, compares,
    formats, or iterates an unclassified key's own protocols. This must run
    as a preflight *before* any staging operation that reconstructs, copies,
    or inserts into a *different* dict object using ``mapping``'s own keys
    (``dict(mapping)`` followed by a keyed assignment, a dict comprehension
    over ``mapping.items()``, or ``target[key] = ...`` for a ``key`` drawn
    from ``mapping``). ``mapping`` already safely holding an unclassified key
    is not by itself enough: Python re-hashes/re-compares a key every time it
    participates in inserting or looking something up in a *different* dict,
    which can invoke a rejected candidate's own ``__hash__``/``__eq__`` again
    during that later staging step, even though the original lookup that
    found ``mapping``'s relevant entry was itself safe. ``mapping`` must
    already be confirmed ``type(mapping) is dict`` by the caller.
    """
    for key in mapping:
        if type(key) is not str:
            return False
    return True


def _safe_find_str_key(mapping: dict[Any, Any], target: str) -> tuple[bool, Any]:
    """Safely locate an exact-``str`` key equal to ``target`` in ``mapping``.

    Returns ``(True, value)`` if found, ``(False, None)`` otherwise. Never
    uses dict-native hash lookup (``in``/``.get()``/``[]``) against
    ``mapping``: that would let CPython's own collision-resolution machinery
    invoke an unrelated, differently-typed key's ``__eq__`` if it happens to
    hash-collide with ``target``. A linear scan that checks
    ``type(key) is str`` *before* any comparison never reaches that hazard --
    ``==`` is only ever evaluated between two already-confirmed genuine
    ``str`` objects. ``mapping`` must already be confirmed
    ``type(mapping) is dict`` by the caller.
    """
    for key, value in mapping.items():
        if type(key) is str and key == target:
            return True, value
    return False, None


def normalize_legend_blocks_shape(frames: Frames) -> Frames:
    """Return ``frames`` with ``_meta.legend_blocks`` in canonical mapping form.

    A no-op when ``_meta`` is not an exact ``dict``, or when it has no
    ``legend_blocks`` root. An explicit ``None`` root is treated as an absent
    declaration and canonicalized to an empty mapping. List form becomes an
    insertion-ordered mapping keyed by resolved identity; mapping form is
    preserved value-for-value (field order included). In both forms a
    pre-existing ``resolved`` facet is removed from every block.

    Raises ``ValueError`` for a non-mapping list member, a duplicate resolved
    identity, or a non-``None`` root that is neither an exact mapping nor an
    exact list.
    """
    meta = frames.get("_meta")
    if type(meta) is not dict:
        # Not an eligible root for this delegate: leave it completely
        # untouched (no lookup, no reconstruction) so the generic
        # metadata_substrate walker rejects it uniformly. Reconstructing an
        # invalid global root into an exact dict merely because it might
        # contain a legend_blocks member would launder it into the accepted
        # substrate outside this delegate's authorized scope.
        return frames
    if not _all_keys_are_exact_str(meta):
        # An unsupported sibling root key would be re-hashed/re-compared by
        # the `new_meta[_ROOT_KEY] = ...` staging assignment below, even
        # though `dict(meta)` itself is safe and even though a legitimate
        # "legend_blocks" member may be present. Leave the whole root
        # untouched for the generic walker's ordinal-key rejection.
        return frames

    found, raw = _safe_find_str_key(meta, _ROOT_KEY)
    if not found:
        return frames

    normalized = _normalize_root(raw)

    new_meta = dict(meta)
    new_meta[_ROOT_KEY] = normalized
    new_frames = dict(frames)
    new_frames["_meta"] = new_meta
    return new_frames


def _normalize_root(raw: Any) -> Any:
    if raw is None:
        return {}
    if type(raw) is dict:
        return _normalize_mapping(raw)
    if type(raw) is list:
        return _normalize_list(raw)
    raise ValueError("_meta.legend_blocks must be a mapping or a list of mappings")


def _normalize_mapping(raw: dict[str, Any]) -> Any:
    if not _all_keys_are_exact_str(raw):
        # An unsupported Legend identity key would be re-hashed by inserting
        # it into the fresh `normalized` dict below. Leave the whole
        # mapping-form root untouched (no reconstruction attempted at all)
        # so the generic walker rejects that key at its own ordinal path.
        return raw
    normalized: dict[str, Any] = {}
    for name, block in raw.items():
        normalized[name] = _strip_resolved(block)
    return normalized


def _normalize_list(raw: list[Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for position, item in enumerate(raw, start=1):
        if type(item) is not dict:
            raise ValueError(
                "_meta.legend_blocks list member at position "
                f"{position} must be a mapping"
            )
        identity = _resolve_identity(item, position)
        if identity in normalized:
            raise ValueError(
                "_meta.legend_blocks list member at position "
                f"{position} resolves to duplicate legend block identity {identity!r}"
            )
        normalized[identity] = _strip_resolved(item)
    return normalized


def _resolve_identity(item: dict[str, Any], position: int) -> str:
    # Authorized identity vocabulary is exact non-empty str, matching the
    # common E3 substrate's own exact-str-key rule (a resolved identity
    # becomes a canonical mapping key). A present but non-str name/id value
    # is safely classified and skipped here -- never given truthiness/`str()`
    # -- and falls through to the next candidate or the positional fallback;
    # it is not silently stringified. Its own value is left unchanged in the
    # block content, where the generic metadata_substrate post-check rejects
    # it like any other out-of-grammar leaf if it is not itself an ordinary
    # Scalar.
    name_found, name = _safe_find_str_key(item, _NAME_KEY)
    if name_found and type(name) is str and name:
        return name
    id_found, block_id = _safe_find_str_key(item, _ID_KEY)
    if id_found and type(block_id) is str and block_id:
        return block_id
    return f"legend_{position}"


def _strip_resolved(block: Any) -> Any:
    if type(block) is not dict:
        # Not an eligible block container: return it completely unchanged
        # (no reconstruction) rather than laundering a Mapping/dict-subclass
        # into an exact dict -- the generic walker rejects it uniformly.
        return block
    if not _all_keys_are_exact_str(block):
        # An unsupported block key would be re-hashed merely by being copied
        # into the comprehension's fresh dict below, even though it is only
        # ever *compared* to "resolved" when already known str. Leave the
        # entire block untouched (including any "resolved" field) so the
        # generic walker rejects the unsupported key at its own ordinal path;
        # the block is rejected either way, so an un-stripped `resolved`
        # field here is harmless.
        return block
    # Every key is already confirmed exact str, so this comprehension only
    # ever inserts/compares already-safe keys. Shallow copy that drops
    # `resolved` while preserving field order; nested containers (entries,
    # placement) are shared but never mutated here.
    return {key: value for key, value in block.items() if key != _RESOLVED_KEY}


__all__ = ["normalize_legend_blocks_shape"]
