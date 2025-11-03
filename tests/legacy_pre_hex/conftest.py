# tests/legacy_pre_hex/conftest.py
import os

def pytest_ignore_collect(path, config):
    # For pytest >=7/8, "path" is a pathlib.Path
    if "tests/legacy_pre_hex" in str(path):
        # Only collect when explicitly requested
        return not os.getenv("RUN_PREHEX")
    return False
