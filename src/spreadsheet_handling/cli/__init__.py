from __future__ import annotations

# Explizite, empfohlene Callables
from .apps.run import main as run_main
from .apps.sheets_pack import main as pack_main
from .apps.sheets_unpack import main as unpack_main

# Bequeme Aliase (keine Deprecation, nur Komfort)
run = run_main
pack = pack_main
unpack = unpack_main

__all__ = [
    "run_main", "pack_main", "unpack_main",  # bevorzugte, explizite API
    "run", "pack", "unpack",                 # bequeme Aliase
]
