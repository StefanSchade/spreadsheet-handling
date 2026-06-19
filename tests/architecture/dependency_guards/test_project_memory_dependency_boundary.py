from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.ftr("FTR-PROJECT-MEMORY-TEMPLATE-RENDER-CONTEXT-P1")

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCT_ROOT = REPO_ROOT / "src" / "spreadsheet_handling"


def _imports_jinja2(module_path: Path) -> bool:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "jinja2" or alias.name.startswith("jinja2.") for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "jinja2" or str(node.module).startswith("jinja2."):
                return True
    return False


def test_jinja2_stays_out_of_product_runtime_code() -> None:
    violations = [
        str(path.relative_to(REPO_ROOT))
        for path in sorted(PRODUCT_ROOT.rglob("*.py"))
        if _imports_jinja2(path)
    ]

    assert not violations, (
        "Jinja2 is project_memory tooling only and must not be imported by product code:\n"
        + "\n".join(violations)
    )
