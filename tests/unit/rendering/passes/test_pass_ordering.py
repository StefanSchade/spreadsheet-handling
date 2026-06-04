import pytest

from spreadsheet_handling.rendering import passes as passes_module
from spreadsheet_handling.rendering.ir import WorkbookIR


pytestmark = pytest.mark.ftr("FTR-REVIEW-001-PASSES-CLEANUP-P3")


EXPECTED_PASS_ORDER = [
    "MetaPass",
    "ValidationPass",
    "StylePass",
    "ProtectionPass",
    "FilterPass",
    "FreezePass",
    "ColumnWidthPass",
    "TextOrientationPass",
    "NamedRangePass",
]


def test_default_passes_order():
    assert [type(pass_).__name__ for pass_ in passes_module.default_passes()] == EXPECTED_PASS_ORDER


def test_apply_all_order_equals_default_passes(monkeypatch):
    seen: list[str] = []

    class RecordingPass:
        def __init__(self, name: str) -> None:
            self.name = name

        def apply(self, ir: WorkbookIR) -> WorkbookIR:
            seen.append(self.name)
            return ir

    monkeypatch.setattr(
        passes_module,
        "default_passes",
        lambda: [RecordingPass(name) for name in EXPECTED_PASS_ORDER],
    )

    passes_module.apply_all(WorkbookIR(), {})

    assert seen == EXPECTED_PASS_ORDER
