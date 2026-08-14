from .operation import contract_xref, expand_xref
from .primitives import _ensure_selector_reference_labels

# _ensure_selector_reference_labels is deliberately re-exported here (not in
# __all__) rather than through `xref_crosstable.primitives` directly: package
# docstrings elsewhere in this package (e.g. dense_axes.py) require consumers
# to reach the public surface via this __init__, not via internal submodules.
# `compact_multiaxis` reuses it as a preflight (see its own module docstring)
# because it performs selector-sensitive work of its own before delegating to
# `contract_xref`/`expand_xref`; the single accepted rule
# (`type(value) is str and value != ""`) must not be duplicated.
__all__ = ["contract_xref", "expand_xref"]
