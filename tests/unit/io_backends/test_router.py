from __future__ import annotations

import pytest

from spreadsheet_handling.io_backends.router import get_loader, get_saver


@pytest.mark.parametrize(
    ("kind", "getter"),
    [
        ("csv_dir", get_loader),
        ("json_dir", get_loader),
        ("json", get_loader),
        ("yaml_dir", get_loader),
        ("yaml", get_loader),
        ("xml_dir", get_loader),
        ("xml", get_loader),
        ("ods", get_loader),
        ("calc", get_loader),
        ("xlsx", get_loader),
        ("csv_dir", get_saver),
        ("json_dir", get_saver),
        ("json", get_saver),
        ("yaml_dir", get_saver),
        ("yaml", get_saver),
        ("xml_dir", get_saver),
        ("xml", get_saver),
        ("ods", get_saver),
        ("calc", get_saver),
        ("xlsx", get_saver),
    ],
)
def test_router_registers_all_first_party_backends(kind, getter) -> None:
    assert callable(getter(kind))


def test_get_loader_raises_value_error_for_unknown_kind() -> None:
    with pytest.raises(ValueError, match="Unknown loader kind: bogus"):
        get_loader("bogus")


def test_get_saver_raises_value_error_for_unknown_kind() -> None:
    with pytest.raises(ValueError, match="Unknown saver kind: bogus"):
        get_saver("bogus")
