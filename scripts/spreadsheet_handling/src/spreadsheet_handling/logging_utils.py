# -*- coding: utf-8 -*-
from __future__ import annotations
import logging
import os
from typing import Optional

DEFAULT_LEVEL = "WARNING"
LOGGER_ROOT = "sheets"

def parse_level(level_str: Optional[str]) -> int:
    if not level_str:
        level_str = DEFAULT_LEVEL
    return getattr(logging, str(level_str).upper(), logging.WARNING)

def setup_logging(level: Optional[str] = None) -> logging.Logger:
    # Env > Parameter > Default
    env_level = os.environ.get("SHEETS_LOG")
    lvl = parse_level(env_level or level)

    logging.basicConfig(
        level=lvl,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logger = logging.getLogger(LOGGER_ROOT)
    logger.setLevel(lvl)
    return logger

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_ROOT}.{name}")

