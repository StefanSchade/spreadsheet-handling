from __future__ import annotations

import pandas as pd

from spreadsheet_handling.domain.transformations.helpers import (
    mark_helpers,
    clean_aux_columns,
)


def test_mark_helpers_and_clean() -> None:
    df = pd.DataFrame(
        [
            {"id": "P1", "name": "A", "fk_branch": "B1"},
            {"id": "P2", "name": "B", "fk_branch": "B2"},
        ]
    )
    frames = {"products": df}

    # mark two cols as helper (with custom prefix)
    step_mark = mark_helpers(sheet="products", cols=["fk_branch", "name"], prefix="helper__")
    frames2 = step_mark(frames)

    assert set(frames2["products"].columns) == {"id", "helper__name", "helper__fk_branch"}

    # cleaning should remove those helper columns again
    step_clean = clean_aux_columns(sheet="products", drop_prefixes=("helper__",))
    frames3 = step_clean(frames2)

    assert set(frames3["products"].columns) == {"id"}
