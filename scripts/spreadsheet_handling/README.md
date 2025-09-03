# spreadsheet-handling

JSON ↔ spreadsheet converter with multi-level headers.  
This package lets you roundtrip nested JSON structures into tabular form (Excel/CSV/ODS) for human editing, and back into JSON for storage or version control.

---

## Features

- Convert JSON with nested objects into spreadsheets with **multi-level headers**.
- Support for multiple backends:
  - Excel (`xlsxwriter` / `openpyxl`)
  - CSV (planned)
  - ODS (planned, via `odfpy`)
- Roundtrip support (spreadsheet → JSON → spreadsheet).
- Helper columns for **human-friendly editing** (e.g. showing IDs alongside names, prefixed with `_` and stripped on export).
- Modular design:
  - `core/` → flattening/unflattening, refs, dataframe builders
  - `io_backends/` → output writers (Excel etc.)
  - `cli/` → command line entrypoints
- Can be embedded in larger projects or used standalone.

---

## Usage (CLI)

Install dependencies (in editable mode):

```bash
make venv
make deps-dev
```

Run a roundtrip conversion:

```bash
# JSON → spreadsheet
json2sheet scripts/spreadsheet_handling/examples/roundtrip_start.json \
    -o scripts/spreadsheet_handling/tmp/tmp.xlsx \
    --levels 3
```

```bash
# spreadsheet → JSON
sheet2json scripts/spreadsheet_handling/tmp/tmp.xlsx \
    -o scripts/spreadsheet_handling/tmp/tmp.json \
    --levels 3
```


The CLI commands json2sheet and sheet2json are installed into your venv as console scripts.

## Usage (Makefile)

The root project ships a Makefile with common tasks:

```bash
make run     # example roundtrip using examples/roundtrip_start.json
make test    # run pytest suite
make clean   # remove tmp, __pycache__, .pytest_cache, lockfiles
```

### Development

Requirements are split:

```
requirements.txt → runtime deps (pandas, xlsxwriter, openpyxl)

requirements-dev.txt → runtime + pytest, hypothesis, etc.
```

To update the lock files:

```
make freeze
make freeze-dev
```

Tests live under tests/ with data fixtures in tests/data/.

## Separation Into Its Own Repo

Right now this code lives under `/scripts/spreadsheet_handling` in a monorepo.

To separate it in the future:

Move the `scripts/spreadsheet_handling/` directory to its own repo root.

Keep the `src/` layout (already in place).

Keep `pyproject.toml`, `requirements*.txt`, and this `README.md`.

Adjust the `Makefile` (drop monorepo paths).

Optionally publish to:

PyPI (for pip installs): pip install .

Docker registry (if you want isolated runtime environments).

Consumers can then depend on it like:

```
[tool.poetry.dependencies]
spreadsheet-handling = { git = "https://github.com/you/spreadsheet-handling.git", tag = "v0.1.0" }
```

This way the package is self-contained and can grow independently.
