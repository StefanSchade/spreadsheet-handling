# Spreadsheet Handling

**Spreadsheet Handling** is a Python toolkit for round-tripping tabular data
between JSON, CSV, and Excel/ODS workbooks while preserving relationships such
as foreign keys, indexes, and hierarchies. It is built around small composable
pipeline steps configured in YAML so that complex spreadsheet models stay
easier to validate, transform, and reimport.

The project is pre-1.0 software. Public behavior is useful for careful
adoption, but API and YAML compatibility are still intentionally allowed to
change while the domain and metadata model settle.

---

## Install

```bash
pip install spreadsheet-handling
```

Requires Python 3.10 or newer.

## Where to go next

- **Try it locally in a few minutes** &mdash;
  the [spreadsheet-handling-demo](https://github.com/StefanSchade/spreadsheet-handling-demo)
  repository walks you through a first-hour tutorial: generate a workbook
  from a normalized JSON model, edit it, reimport it, and verify the
  canonical JSON stays clean.
- **Read the user guide (latest release)** &mdash;
  <https://stefanschade.github.io/spreadsheet-handling-pages/versions/v0.2.1/core/user-guide/>.
- **Browse documentation by version** &mdash;
  <https://stefanschade.github.io/spreadsheet-handling-pages/>
  is the per-release archive portal; it carries the latest-release banner
  and a list of every published version.

---

## Features

- Convert JSON ↔ CSV/Excel (XLSX) and ODS workbooks with round-tripping support
- Detect and enforce foreign key relationships
- Validate spreadsheet structures (naming rules, uniqueness, etc.)
- Orchestrate multi-sheet pipelines via YAML configs
- Extensible: plug in new backends and transformation steps

---

### License

This project is licensed under the terms of the MIT License.
See [LICENSE](LICENSE) for details.
