from __future__ import annotations

from pathlib import Path

import pytest

from project_memory.plugins.render_context import build_render_context, render_current_context


def test_build_render_context_includes_concern_steering() -> None:
    context = build_render_context()

    assert context["concerns"]
    ct = next(
        (c for c in context["concerns"] if c["id"] == "CONC-DOMAIN-META-SEMANTICS"),
        None,
    )
    assert ct is not None, "CONC-DOMAIN-META-SEMANTICS not found in concerns"
    assert ct["events"]
    assert "diagnostics" in context


def test_render_current_context_uses_asciidoc_templates(tmp_path: Path) -> None:
    pytest.importorskip("jinja2")

    output = render_current_context(tmp_path / "current_context.adoc")
    text = output.read_text(encoding="utf-8")

    assert "== Concerns" in text
    assert "CONC-DOMAIN-META-SEMANTICS" in text
    assert "== Current Findings" in text
    assert "== Active FTRs" in text
    assert "== Review Takeaways" in text
    assert "== Diagnostics" in text
