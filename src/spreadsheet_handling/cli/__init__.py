from __future__ import annotations

# Explicit recommended callables.
from .apps.run import main as run_main
from .apps.sheets_pack import main as pack_main
from .apps.sheets_unpack import main as unpack_main

# Convenience aliases, not deprecations.
run = run_main
pack = pack_main
unpack = unpack_main

__all__ = [
    "run_main", "pack_main", "unpack_main",  # preferred explicit API
    "run", "pack", "unpack",                 # convenience aliases
]
