"""Tests for FTR-LOOKUP-HELPER-FORMULA-MODE-P4A.

Covers:
- enrich_lookup with helper_value_mode='formula' emits LookupFormulaSpec cells
- Formula sheet-name resolution in select_render_frames
- XLSX end-to-end rendering of lookup formulas
- ODS rendering parity
- Backward compatibility: value mode remains default
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from spreadsheet_handling.domain.transformations.enrich_lookup import enrich_lookup
from spreadsheet_handling.core.formulas import LookupFormulaSpec

pytestmark = pytest.mark.ftr("FTR-LOOKUP-HELPER-FORMULA-MODE-P4A")


def _frames() -> dict[str, Any]:
    variables = pd.DataFrame({
        "variable_id": ["v1", "v2", "v3"],
        "label_de": ["Eins", "Zwei", "Drei"],
        "data_type": ["string", "int", "bool"],
    })
    matrix = pd.DataFrame({
        "variable_id": ["v1", "v2"],
        "P-001": ["E", "A"],
    })
    return {
        "variables": variables,
        "matrix_raw": matrix,
        "_meta": {},
    }


class TestFormulaMode:

    def test_formula_mode_emits_lookup_formula_specs(self) -> None:
        frames = _frames()
        out = enrich_lookup(
            frames,
            source="matrix_raw",
            lookup="variables",
            output="matrix",
            key="variable_id",
            helpers={"fields": ["label_de"]},
            missing="empty",
            helper_value_mode="formula",
        )
        df = out["matrix"]
        assert "label_de" in df.columns
        cell = df["label_de"].iloc[0]
        assert isinstance(cell, LookupFormulaSpec)
        assert cell.source_key_column == "variable_id"
        assert cell.lookup_sheet == "variables"
        assert cell.lookup_key_column == "variable_id"
        assert cell.lookup_value_column == "label_de"

    def test_formula_mode_multiple_fields(self) -> None:
        frames = _frames()
        out = enrich_lookup(
            frames,
            source="matrix_raw",
            lookup="variables",
            output="matrix",
            key="variable_id",
            helpers={"fields": ["label_de", "data_type"]},
            missing="empty",
            helper_value_mode="formula",
        )
        df = out["matrix"]
        for field in ("label_de", "data_type"):
            cell = df[field].iloc[0]
            assert isinstance(cell, LookupFormulaSpec)
            assert cell.lookup_value_column == field

    @pytest.mark.ftr("FTR-REVIEW-001-FORMULAS-CORE-MOVE-P3")
    def test_formula_mode_rejects_fail_missing_mode(self) -> None:
        frames = _frames()

        with pytest.raises(ValueError, match="missing='fail'"):
            enrich_lookup(
                frames,
                source="matrix_raw",
                lookup="variables",
                output="matrix",
                key="variable_id",
                helpers={"fields": ["label_de"]},
                missing="fail",
                helper_value_mode="formula",
            )

    def test_value_mode_remains_default(self) -> None:
        frames = _frames()
        out = enrich_lookup(
            frames,
            source="matrix_raw",
            lookup="variables",
            output="matrix",
            key="variable_id",
            helpers={"fields": ["label_de"]},
            missing="empty",
        )
        df = out["matrix"]
        assert df["label_de"].iloc[0] == "Eins"
        assert not isinstance(df["label_de"].iloc[0], LookupFormulaSpec)

    def test_explicit_values_mode_still_merges(self) -> None:
        frames = _frames()
        out = enrich_lookup(
            frames,
            source="matrix_raw",
            lookup="variables",
            output="matrix",
            key="variable_id",
            helpers={"fields": ["label_de"]},
            missing="empty",
            helper_value_mode="values",
        )
        df = out["matrix"]
        assert df["label_de"].iloc[0] == "Eins"

    def test_formula_mode_writes_provenance(self) -> None:
        frames = _frames()
        out = enrich_lookup(
            frames,
            source="matrix_raw",
            lookup="variables",
            output="matrix",
            key="variable_id",
            helpers={"fields": ["label_de"]},
            missing="empty",
            helper_value_mode="formula",
        )
        prov = out["_meta"]["derived"]["sheets"]["matrix"]["enrich_lookup"]
        assert prov["helper_columns"] == ["label_de"]
        assert prov["lookup"] == "variables"

    def test_invalid_value_mode_raises(self) -> None:
        frames = _frames()
        with pytest.raises(ValueError, match="helper_value_mode"):
            enrich_lookup(
                frames,
                source="matrix_raw",
                lookup="variables",
                output="matrix",
                key="variable_id",
                helpers={"fields": ["label_de"]},
                missing="empty",
                helper_value_mode="invalid",
            )


class TestFormulaSheetNameResolution:

    def test_formulas_resolve_to_physical_sheet_names(self) -> None:
        from spreadsheet_handling.rendering.frame_selection import select_render_frames

        formula = LookupFormulaSpec(
            source_key_column="variable_id",
            lookup_sheet="variables",
            lookup_key_column="variable_id",
            lookup_value_column="label_de",
            missing="",
        )
        frames = {
            "variables": pd.DataFrame({
                "variable_id": ["v1"],
                "label_de": ["Eins"],
            }),
            "matrix": pd.DataFrame({
                "variable_id": ["v1"],
                "label_de": [formula],
            }),
            "_meta": {
                "workbook_view": {
                    "sheets": [
                        {"frame": "variables", "sheet": "Entities"},
                        {"frame": "matrix", "sheet": "Matrix"},
                    ],
                }
            },
        }
        selected = select_render_frames(frames, frames["_meta"])

        cell = selected["Matrix"]["label_de"].iloc[0]
        assert isinstance(cell, LookupFormulaSpec)
        assert cell.lookup_sheet == "Entities"

    def test_no_rename_preserves_frame_name(self) -> None:
        from spreadsheet_handling.rendering.frame_selection import select_render_frames

        formula = LookupFormulaSpec(
            source_key_column="variable_id",
            lookup_sheet="variables",
            lookup_key_column="variable_id",
            lookup_value_column="label_de",
            missing="",
        )
        frames = {
            "variables": pd.DataFrame({
                "variable_id": ["v1"],
                "label_de": ["Eins"],
            }),
            "matrix": pd.DataFrame({
                "variable_id": ["v1"],
                "label_de": [formula],
            }),
            "_meta": {
                "workbook_view": {
                    "sheets": [
                        {"frame": "variables", "sheet": "variables"},
                        {"frame": "matrix", "sheet": "matrix"},
                    ],
                }
            },
        }
        selected = select_render_frames(frames, frames["_meta"])

        cell = selected["matrix"]["label_de"].iloc[0]
        assert isinstance(cell, LookupFormulaSpec)
        assert cell.lookup_sheet == "variables"


class TestXlsxLookupFormulaRendering:

    def test_xlsx_renders_xlookup_formulas(self, tmp_path: Path) -> None:
        from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
        from spreadsheet_handling.rendering.flow import (
            apply_ir_passes,
            build_render_plan,
            default_p1_passes,
        )
        from spreadsheet_handling.io_backends.xlsx.openpyxl_renderer import render_workbook
        from openpyxl import load_workbook

        formula = LookupFormulaSpec(
            source_key_column="variable_id",
            lookup_sheet="variables",
            lookup_key_column="variable_id",
            lookup_value_column="label_de",
            missing="",
        )
        frames = {
            "variables": pd.DataFrame({
                "variable_id": ["v1", "v2"],
                "label_de": ["Eins", "Zwei"],
            }),
            "matrix": pd.DataFrame({
                "variable_id": ["v1", "v2"],
                "label_de": [formula, formula],
            }),
        }
        ir = compose_workbook(frames, None)
        apply_ir_passes(ir, default_p1_passes())
        plan = build_render_plan(ir)

        out = tmp_path / "formula.xlsx"
        render_workbook(plan, out)

        wb = load_workbook(out)
        ws = wb["matrix"]
        cell = ws.cell(row=2, column=2)
        assert cell.value is not None
        assert "XLOOKUP" in str(cell.value)
        assert "variables" in str(cell.value)


class TestOdsLookupFormulaRendering:

    def test_ods_renders_xlookup_formulas(self, tmp_path: Path) -> None:
        from spreadsheet_handling.rendering.composer.layout_composer import compose_workbook
        from spreadsheet_handling.rendering.flow import (
            apply_ir_passes,
            build_render_plan,
            default_p1_passes,
        )
        from spreadsheet_handling.io_backends.ods.odf_renderer import render_workbook

        formula = LookupFormulaSpec(
            source_key_column="variable_id",
            lookup_sheet="variables",
            lookup_key_column="variable_id",
            lookup_value_column="label_de",
            missing="",
        )
        frames = {
            "variables": pd.DataFrame({
                "variable_id": ["v1", "v2"],
                "label_de": ["Eins", "Zwei"],
            }),
            "matrix": pd.DataFrame({
                "variable_id": ["v1", "v2"],
                "label_de": [formula, formula],
            }),
        }
        ir = compose_workbook(frames, None)
        apply_ir_passes(ir, default_p1_passes())
        plan = build_render_plan(ir)

        out = tmp_path / "formula.ods"
        render_workbook(plan, out)
        assert out.exists()


class TestEndToEndFormulaEnrichment:

    def test_full_pipeline_enrich_render_xlsx(self, tmp_path: Path) -> None:
        from spreadsheet_handling.domain.workbook_views import configure_workbook_view
        from spreadsheet_handling.io_backends.spreadsheet_contract import (
            build_spreadsheet_render_plan,
        )
        from spreadsheet_handling.io_backends.xlsx.openpyxl_renderer import render_workbook
        from openpyxl import load_workbook

        variables = pd.DataFrame({
            "variable_id": ["v1", "v2"],
            "label_de": ["Eins", "Zwei"],
        })
        matrix_raw = pd.DataFrame({
            "variable_id": ["v1", "v2"],
            "P-001": ["E", "A"],
        })
        frames: dict[str, Any] = {
            "variables": variables,
            "matrix_raw": matrix_raw,
            "_meta": {},
        }

        enriched = enrich_lookup(
            frames,
            source="matrix_raw",
            lookup="variables",
            output="matrix",
            key="variable_id",
            helpers={"fields": ["label_de"]},
            missing="empty",
            helper_value_mode="formula",
        )

        viewed = configure_workbook_view(
            enriched,
            sheets=[
                {"frame": "variables", "sheet": "Entities"},
                {"frame": "matrix", "sheet": "Matrix"},
            ],
        )

        plan = build_spreadsheet_render_plan(viewed, viewed.get("_meta"))
        out = tmp_path / "e2e.xlsx"
        render_workbook(plan, out)

        wb = load_workbook(out)
        ws = wb["Matrix"]
        # Matrix columns: variable_id (1), P-001 (2), label_de helper (3)
        cell = ws.cell(row=2, column=3)
        formula_text = str(cell.value)
        assert "XLOOKUP" in formula_text
        # Formula should reference 'Entities' (physical sheet name), not 'variables'
        assert "Entities" in formula_text


# ---------------------------------------------------------------------------
# Review 001 IMP-004: asymmetric formula-mode regression coverage
# (FTR-XREF-LOOKUP-HELPER-SUBSTITUTION-P4A2 Slice 1)
# ---------------------------------------------------------------------------

_asymmetric = pytest.mark.ftr("FTR-XREF-LOOKUP-HELPER-SUBSTITUTION-P4A2")


def _asymmetric_frames() -> dict[str, Any]:
    """Worldbuilding-shaped source keyed by ``story_id`` against lookup ``id``."""
    stories = pd.DataFrame({
        "id": ["s1", "s2"],
        "title": ["First", "Second"],
    })
    matrix = pd.DataFrame({
        "story_id": ["s1", "s2"],
        "P-001": ["E", "A"],
    })
    return {"stories": stories, "matrix_raw": matrix, "_meta": {}}


class TestAsymmetricFormulaMode:

    @_asymmetric
    def test_asymmetric_formula_spec_uses_distinct_key_columns(self) -> None:
        frames = _asymmetric_frames()
        out = enrich_lookup(
            frames,
            source="matrix_raw",
            lookup="stories",
            output="matrix",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["title"]},
            missing="empty",
            helper_value_mode="formula",
        )
        df = out["matrix"]
        cell = df["title"].iloc[0]
        assert isinstance(cell, LookupFormulaSpec)
        assert cell.source_key_column == "story_id"
        assert cell.lookup_key_column == "id"
        assert cell.lookup_value_column == "title"
        assert cell.lookup_sheet == "stories"
        # Source key preserved; lookup key does not leak.
        assert list(df["story_id"]) == ["s1", "s2"]
        assert "id" not in df.columns

    @_asymmetric
    def test_asymmetric_formula_helper_placement_before_key(self) -> None:
        frames = _asymmetric_frames()
        out = enrich_lookup(
            frames,
            source="matrix_raw",
            lookup="stories",
            output="matrix",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["title"]},
            order={"helper_position": "before_key"},
            missing="empty",
            helper_value_mode="formula",
        )
        assert list(out["matrix"].columns) == ["title", "story_id", "P-001"]

    @_asymmetric
    def test_asymmetric_formula_provenance_records_distinct_keys(self) -> None:
        frames = _asymmetric_frames()
        out = enrich_lookup(
            frames,
            source="matrix_raw",
            lookup="stories",
            output="matrix",
            source_key="story_id",
            lookup_key="id",
            helpers={"fields": ["title"]},
            missing="empty",
            helper_value_mode="formula",
        )
        prov = out["_meta"]["derived"]["sheets"]["matrix"]["enrich_lookup"]
        assert prov["source_key"] == "story_id"
        assert prov["lookup_key"] == "id"
        assert prov["helper_columns"] == ["title"]
        assert "on" not in prov

    @_asymmetric
    def test_asymmetric_formula_helper_equals_source_key_rejected(self) -> None:
        stories = pd.DataFrame({
            "id": ["s1", "s2"],
            "story_id": ["x", "y"],
            "title": ["First", "Second"],
        })
        frames = {"stories": stories, "matrix_raw": _asymmetric_frames()["matrix_raw"], "_meta": {}}
        with pytest.raises(ValueError, match="collides with the asymmetric source key"):
            enrich_lookup(
                frames,
                source="matrix_raw",
                lookup="stories",
                output="matrix",
                source_key="story_id",
                lookup_key="id",
                helpers={"fields": ["story_id"]},
                missing="empty",
                helper_value_mode="formula",
            )
        # Collision fails before any formula assignment: no output frame written.
        assert "matrix" not in frames

    @_asymmetric
    def test_asymmetric_formula_helper_equals_lookup_key_rejected(self) -> None:
        frames = _asymmetric_frames()
        with pytest.raises(ValueError, match="collides with the asymmetric lookup key"):
            enrich_lookup(
                frames,
                source="matrix_raw",
                lookup="stories",
                output="matrix",
                source_key="story_id",
                lookup_key="id",
                helpers={"fields": ["id"]},
                missing="empty",
                helper_value_mode="formula",
            )
        assert "matrix" not in frames


def _nontrivial_asymmetric_frames() -> dict[str, Any]:
    """Nontrivial layout that makes lookup argument order load-bearing (IMP-004).

    * source key ``story_id`` is *not* the first source column (col B by
      default; col C after ``before_key`` reordering);
    * the lookup key ``id`` is *not* the first lookup column (col D) and the
      lookup value ``title`` is at a *different, non-adjacent* position (col B),
      separated by unrelated columns.

    A renderer that emitted positional columns, or swapped the XLOOKUP key and
    value ranges, would produce a different exact formula and fail the tests.
    """
    entities = pd.DataFrame({
        "misc1": ["m1", "m2"],   # col A (unrelated)
        "title": ["First", "Second"],  # col B (lookup value)
        "misc2": ["x", "y"],     # col C (unrelated)
        "id": ["s1", "s2"],      # col D (lookup key)
    })
    matrix = pd.DataFrame({
        "P_lead": ["p1", "p2"],  # col A (leading non-key column)
        "story_id": ["s1", "s2"],  # col B (source key, not first)
        "extra": ["e1", "e2"],   # col C
    })
    return {"entities": entities, "matrix_raw": matrix, "_meta": {}}


def _render_asymmetric_matrix(helper_position: str):
    """Enrich + view + return a render plan for the nontrivial layout.

    Physical sheet name ``"Entity Lookup"`` intentionally contains a space to
    exercise sheet-name quoting in both backends.
    """
    from spreadsheet_handling.domain.workbook_views import configure_workbook_view
    from spreadsheet_handling.io_backends.spreadsheet_contract import (
        build_spreadsheet_render_plan,
    )

    enriched = enrich_lookup(
        _nontrivial_asymmetric_frames(),
        source="matrix_raw",
        lookup="entities",
        output="matrix",
        source_key="story_id",
        lookup_key="id",
        helpers={"fields": ["title"]},
        order={"helper_position": helper_position},
        missing="empty",
        helper_value_mode="formula",
    )
    viewed = configure_workbook_view(
        enriched,
        sheets=[
            {"frame": "entities", "sheet": "Entity Lookup"},
            {"frame": "matrix", "sheet": "Matrix"},
        ],
    )
    return build_spreadsheet_render_plan(viewed, viewed.get("_meta"))


class TestAsymmetricFormulaRendering:
    """Load-bearing ordered-argument assertions (review R002-IMP-004).

    Exact formula text is asserted so a swap of the XLOOKUP key and value
    ranges — or a positional renderer — fails. The lookup key ``id`` lives at
    column D and the value ``title`` at column B, so the correct order is
    ``key range = $D$..``, ``value range = $B$..``.
    """

    @_asymmetric
    def test_xlsx_default_after_data_exact_ordered_formula(self, tmp_path: Path) -> None:
        from spreadsheet_handling.io_backends.xlsx.openpyxl_renderer import render_workbook
        from openpyxl import load_workbook

        out = tmp_path / "asym.xlsx"
        render_workbook(_render_asymmetric_matrix("after_data"), out)

        ws = load_workbook(out)["Matrix"]
        # Matrix cols: P_lead(A), story_id(B, source key), extra(C), title(D helper).
        formula = str(ws.cell(row=2, column=4).value)
        assert formula == (
            "=XLOOKUP($B2,'Entity Lookup'!$D$2:$D$3,'Entity Lookup'!$B$2:$B$3,\"\")"
        )

    @_asymmetric
    def test_xlsx_before_key_exact_ordered_formula(self, tmp_path: Path) -> None:
        from spreadsheet_handling.io_backends.xlsx.openpyxl_renderer import render_workbook
        from openpyxl import load_workbook

        out = tmp_path / "asym.xlsx"
        render_workbook(_render_asymmetric_matrix("before_key"), out)

        ws = load_workbook(out)["Matrix"]
        # Matrix cols: P_lead(A), title(B helper), story_id(C, source key), extra(D).
        formula = str(ws.cell(row=2, column=2).value)
        assert formula == (
            "=XLOOKUP($C2,'Entity Lookup'!$D$2:$D$3,'Entity Lookup'!$B$2:$B$3,\"\")"
        )

    @_asymmetric
    def test_ods_default_after_data_exact_ordered_formula(self, tmp_path: Path) -> None:
        from spreadsheet_handling.io_backends.ods.odf_renderer import render_workbook
        from odf.opendocument import load as load_ods
        from odf.table import TableCell

        out = tmp_path / "asym.ods"
        render_workbook(_render_asymmetric_matrix("after_data"), out)

        doc = load_ods(str(out))
        formulas = [
            c.getAttribute("formula")
            for c in doc.getElementsByType(TableCell)
            if c.getAttribute("formula")
        ]
        assert formulas[0] == (
            "of:=COM.MICROSOFT.XLOOKUP([.B2];['Entity Lookup'.D2:'Entity Lookup'.D3];"
            "['Entity Lookup'.B2:'Entity Lookup'.B3];\"\")"
        )

    @_asymmetric
    def test_ods_before_key_exact_ordered_formula(self, tmp_path: Path) -> None:
        from spreadsheet_handling.io_backends.ods.odf_renderer import render_workbook
        from odf.opendocument import load as load_ods
        from odf.table import TableCell

        out = tmp_path / "asym.ods"
        render_workbook(_render_asymmetric_matrix("before_key"), out)

        doc = load_ods(str(out))
        formulas = [
            c.getAttribute("formula")
            for c in doc.getElementsByType(TableCell)
            if c.getAttribute("formula")
        ]
        assert formulas[0] == (
            "of:=COM.MICROSOFT.XLOOKUP([.C2];['Entity Lookup'.D2:'Entity Lookup'.D3];"
            "['Entity Lookup'.B2:'Entity Lookup'.B3];\"\")"
        )


class TestEqualNameAsymmetricFormulaCollision:
    """Equal-name explicit asymmetric formula collision coverage (R002-IMP-001)."""

    @_asymmetric
    def test_equal_name_helper_equals_key_rejected_formula(self) -> None:
        frames = {
            "stories": pd.DataFrame({"id": ["s1", "s2"], "title": ["First", "Second"]}),
            "matrix_raw": pd.DataFrame({"id": ["s1", "s2"], "P-001": ["E", "A"]}),
            "_meta": {},
        }
        with pytest.raises(ValueError, match="authoritative source key"):
            enrich_lookup(
                frames,
                source="matrix_raw",
                lookup="stories",
                output="matrix",
                source_key="id",
                lookup_key="id",
                helpers={"fields": ["id"]},
                missing="empty",
                helper_value_mode="formula",
            )
        assert "matrix" not in frames


class TestFormulaDuplicateHelperRejection:
    """Duplicate-helper rejection in formula mode (review R003-MIN-001).

    The common ``_check_duplicate_helper_fields`` guard runs before value-mode
    or placement branching, so it is mode- and position-independent. These
    tracked cases prove it for formula/default and formula/`before_key` in both
    symmetric and asymmetric modes; a later placement- or mode-specific refactor
    would fail here. The runtime rule itself is unchanged.
    """

    @pytest.mark.ftr("FTR-XREF-LOOKUP-HELPER-SUBSTITUTION-P4A2")
    @pytest.mark.parametrize("helper_position", ["after_data", "before_key"])
    def test_symmetric_formula_duplicate_helper_rejected(self, helper_position) -> None:
        frames = _frames()  # symmetric key=variable_id, lookup=variables
        with pytest.raises(ValueError, match="Duplicate helper field"):
            enrich_lookup(
                frames,
                source="matrix_raw",
                lookup="variables",
                output="matrix",
                key="variable_id",
                helpers={"fields": ["label_de", "label_de"]},
                order={"helper_position": helper_position},
                missing="empty",
                helper_value_mode="formula",
            )
        assert "matrix" not in frames

    @_asymmetric
    @pytest.mark.parametrize("helper_position", ["after_data", "before_key"])
    def test_asymmetric_formula_duplicate_helper_rejected(self, helper_position) -> None:
        frames = _asymmetric_frames()  # source_key=story_id, lookup_key=id
        with pytest.raises(ValueError, match="Duplicate helper field"):
            enrich_lookup(
                frames,
                source="matrix_raw",
                lookup="stories",
                output="matrix",
                source_key="story_id",
                lookup_key="id",
                helpers={"fields": ["title", "title"]},
                order={"helper_position": helper_position},
                missing="empty",
                helper_value_mode="formula",
            )
        assert "matrix" not in frames
