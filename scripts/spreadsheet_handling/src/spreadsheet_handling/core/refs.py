# core/refs.py
from typing import Iterable

def add_helper_columns(records: list[dict], ref_specs: list[dict]) -> list[dict]:
    """
    ref_specs: z.B. [{"path_id": "char.id", "helper_path": "_char.name", "resolver": callable}]
    resolver(id) -> name
    """
    for r in records:
        for spec in ref_specs:
            pid = spec["path_id"]; hp = spec["helper_path"]; res = spec["resolver"]
            if pid in r:
                try:
                    r[hp] = res(r[pid])
                except Exception:
                    r[hp] = ""
    return records

# xlsxwriter-Formeln (optional):
def write_vlookup_formula(ws, row, col, lookup_value_cell, table_range, result_col_index):
    formula = f'=VLOOKUP({lookup_value_cell},{table_range},{result_col_index},0)'
    ws.write_formula(row, col, formula)

