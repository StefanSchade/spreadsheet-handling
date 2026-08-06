"""System-Python (python3-uno) helper for real LibreOffice interoperability
checks.

Opens a real ODS file in headless LibreOffice via the UNO bridge, forces
recalculation, and reports the formula/value/error state of named cells --
optionally after editing a source cell and recalculating again.

This module is invoked as a standalone script with the *system* python3
that LibreOffice ships python3-uno against, not the project's virtualenv
interpreter -- the `uno`/`unohelper` modules are not pip-installable and are
normally absent from a project venv. It intentionally has no dependency on
`spreadsheet_handling` or any third-party package; only the standard library
plus `uno` are required.

Usage:
    python3 libreoffice_uno_probe.py <ods_path> <port> <spec_json>

`spec_json` is a JSON object:
{
  "sheet": "Places",
  "cells": [[2, 1], [3, 1]],   // 0-based (col, row) read every step
  "edits": [                   // sequence of 0-based (col, row, value) edits;
    [1, 1, "R-UNKNOWN"],       // applied one at a time, each followed by a
    [1, 1, "R-2"]              // full recalculation and another cell read
  ]
}

Prints one JSON object to stdout:
{
  "initial": [{"formula": str, "string": str, "error": int}, ...],
  "after_edits": [[{...}, ...], ...]   // one entry per edit in `edits`
}
"""

from __future__ import annotations

import json
import sys
import time

import uno
from com.sun.star.beans import PropertyValue


def _mk_prop(name: str, value: object) -> PropertyValue:
    prop = PropertyValue()
    prop.Name = name
    prop.Value = value
    return prop


def _connect(port: str):
    local_context = uno.getComponentContext()
    resolver = local_context.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local_context
    )
    last_exc: Exception | None = None
    for _ in range(60):
        try:
            return resolver.resolve(
                f"uno:socket,host=localhost,port={port};urp;StarOffice.ComponentContext"
            )
        except Exception as exc:  # noqa: BLE001 - retry loop probing readiness
            last_exc = exc
            time.sleep(0.5)
    raise RuntimeError(f"could not connect to soffice on port {port}") from last_exc


def _read_cells(sheet, cells: list[list[int]]) -> list[dict[str, object]]:
    results = []
    for col, row in cells:
        cell = sheet.getCellByPosition(col, row)
        results.append(
            {
                "formula": cell.getFormula(),
                "string": cell.getString(),
                "error": cell.getError(),
            }
        )
    return results


def main() -> None:
    ods_path, port, spec_json = sys.argv[1], sys.argv[2], sys.argv[3]
    spec = json.loads(spec_json)

    ctx = _connect(port)
    desktop = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", ctx
    )
    doc = desktop.loadComponentFromURL(
        "file://" + ods_path, "_blank", 0, (_mk_prop("Hidden", True),)
    )
    try:
        doc.calculateAll()
        sheet = doc.Sheets.getByName(spec["sheet"])

        report: dict[str, object] = {
            "initial": _read_cells(sheet, spec["cells"]),
            "after_edits": [],
        }

        for col, row, value in spec.get("edits", []):
            sheet.getCellByPosition(col, row).setString(value)
            doc.calculateAll()
            report["after_edits"].append(_read_cells(sheet, spec["cells"]))

        print(json.dumps(report))
    finally:
        doc.close(False)


if __name__ == "__main__":
    main()
