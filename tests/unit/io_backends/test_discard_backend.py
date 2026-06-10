from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from spreadsheet_handling.io_backends.discard_backend import save_discard
from spreadsheet_handling.io_backends.router import get_loader, get_saver

pytestmark = pytest.mark.ftr("FTR-SCHEMA-EVOLUTION-OPERATIONS")


def test_get_saver_returns_discard_saver() -> None:
    assert get_saver("discard") is save_discard


def test_get_loader_discard_fails_clearly() -> None:
    with pytest.raises(ValueError, match="Unknown loader kind: discard"):
        get_loader("discard")


@pytest.mark.parametrize("path_name", ["-", "__discard__", "would_be_output"])
def test_discard_saver_writes_nothing(tmp_path: Path, path_name: str) -> None:
    output_path = tmp_path / path_name
    frames = {"items": pd.DataFrame({"id": ["i1"], "name": ["Item"]})}

    save_discard(frames, str(output_path))

    assert not output_path.exists()
    assert list(tmp_path.iterdir()) == []
