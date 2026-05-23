# Spreadsheet Handling

**Spreadsheet Handling** is a Python toolkit for round-tripping tabular data
between JSON, CSV, and Excel/ODS workbooks while preserving relationships such
as foreign keys, indexes, and hierarchies. It is built around small composable
pipeline steps configured in YAML so that complex spreadsheet models stay
easier to validate, transform, and reimport.

The project is in beta.

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
  <https://stefanschade.github.io/spreadsheet-handling-pages/latest/core/user-guide/>.
- **Browse documentation by version** &mdash;
  <https://stefanschade.github.io/spreadsheet-handling-pages/>
  is the per-release archive portal; it carries the latest-release banner
  and a list of every published version.

---

## Features

- Convert JSON ↔ CSV/Excel (XLSX) with round-tripping support
- Detect and enforce foreign key relationships
- Validate spreadsheet structures (naming rules, uniqueness, etc.)
- Orchestrate multi-sheet pipelines via YAML configs
- Extensible: plug in new backends and transformation steps

---

### AI Usage & Position Statement

- AI tools are used at all levels of this project: requirement analysis, solution design, coding.
- Human oversight, testing, and review remain essential. AI augments reasoning and speed but does not replace engineering judgment.
- Quality and maintainability are goals treated with priority; AI contributes to these.

*Industry trends support this approach:*
according to the [JetBrains Developer Ecosystem 2025 survey published by *Golem.de*](https://www.golem.de/news/umfrage-unter-24-000-entwicklern-gesamtes-berufsfeld-befindet-sich-im-wandel-2510-188855.html), AI adoption is already pervasive and considered a core competency.

### License

This project is licensed under the terms of the MIT License.
See [LICENSE](LICENSE) for details.
