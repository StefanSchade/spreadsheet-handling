from __future__ import annotations
import logging


def setup_logging(verbosity: int) -> None:
    """
    - 0  -> WARNING
    - 1  -> INFO
    - 2+ -> DEBUG
    """
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s  %(name)s:%(message)s")
