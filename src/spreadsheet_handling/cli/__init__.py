from __future__ import annotations

# Explicit recommended callables.
from .apps.run import main as run_main
from .apps.example_json_to_xlsx import main as example_json_to_xlsx_main
from .apps.example_xlsx_to_json import main as example_xlsx_to_json_main

__all__ = [
    "run_main",
    "example_json_to_xlsx_main",
    "example_xlsx_to_json_main",
]
