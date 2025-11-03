import pandas as pd
from spreadsheet_handling.engine.orchestrator import Engine
from spreadsheet_handling.core.indexing import level0_series


def test_apply_fks_adds_helper_column(tmp_path):
    frames = {
        "Guten Morgen": pd.DataFrame([{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}]),
        "Bestellungen": pd.DataFrame(
            [
                {"bestellnr": "B-1", "id_(Guten_Morgen)": 1},
                {"bestellnr": "B-2", "id_(Guten_Morgen)": 2},
            ]
        ),
    }
    eng = Engine(
        {
            "levels": 3,
            "id_field": "id",
            "label_field": "name",
            "helper_prefix": "_",
            "detect_fk": True,
        }
    )
    out = eng.apply_fks(frames)

    dfq = out["Bestellungen"]

    # Spaltennamen robust auf „Level-0“ normalisieren:
    # - echter MultiIndex  -> nimm Level 0
    # - einfacher Index mit Tuple-Elementen -> nimm Element 0 des Tuples
    # - sonst: nimm den Namen direkt
    if isinstance(dfq.columns, pd.MultiIndex):
        lvl0 = list(dfq.columns.get_level_values(0))
    else:

        def col0(c):
            return c[0] if isinstance(c, tuple) and len(c) > 0 else c

        lvl0 = [col0(c) for c in dfq.columns]

    helper_cols0 = [c for c in lvl0 if isinstance(c, str) and c.startswith("_")]
    assert helper_cols0, f"no helper column found in level-0 of {lvl0}"

    # Werte prüfen – robust via level0_series (funktioniert bei MI und Tuple-Namen)
    s = level0_series(dfq, helper_cols0[0])
    assert s.tolist() == ["Alpha", "Beta"]
