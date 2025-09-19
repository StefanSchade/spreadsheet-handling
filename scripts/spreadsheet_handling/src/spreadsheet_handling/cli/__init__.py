from __future__ import annotations

# Re-export legacy CLIs (pack/unpack) as before
from .sheets_pack import run_pack as pack  # noqa: F401
from .sheets_unpack import run_unpack as unpack  # noqa: F401

# Expose the generic runner *optionally* to avoid import-time failures if its deps are missing
try:
    from . import run  # noqa: F401
except Exception:
    # Keep package import working even if run.py's optional deps aren't available yet.
    run = None  # type: ignore[assignment]

__all__ = ["pack", "unpack", "run"]
