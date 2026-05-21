# Spreadsheet Handling

**Spreadsheet Handling** is a Python toolkit for converting and orchestrating tabular data.  
It converts between JSON, CSV, and Excel (XLSX/ODS) while preserving relationships such as foreign keys, indexes, and hierarchies.  
The goal is to make complex spreadsheet models easier to validate, transform, and round-trip into structured formats.

This project is still beta. The main user entry point is the
[spreadsheet-handling-demo](https://github.com/StefanSchade/spreadsheet-handling-demo)
repository, which contains the runnable prototype integration. Published
documentation is available at
[stefanschade.github.io/spreadsheet-handling-pages](https://stefanschade.github.io/spreadsheet-handling-pages/);
it is being expanded gradually.

---

## Features

- Convert JSON ↔ CSV/Excel with round-tripping support
- Detect and enforce foreign key relationships
- Validate spreadsheet structures (naming rules, uniqueness, etc.)
- Orchestrate multi-sheet pipelines via YAML configs
- Extensible: plug in new backends and transformation steps

---

## Installation

```bash
# clone repo
git clone https://github.com/StefanSchade/spreadsheet-handling.git
cd spreadsheet-handling

# set up environment
make setup
```

## Usage

### Run a configurable pipeline:

```bash
sheets-run --config sheets.yaml --profile demo
```

### Try the reference shortcut commands:

```bash
sheets-example-json-to-xlsx examples/json -o demo.xlsx
sheets-example-xlsx-to-json demo.xlsx -o demo_out
```

### Run full test suite:

```bash
make test
```

### AI Usage & Position Statement

- AI tools are used at all levels of this project: requirement analysis, solution design, coding.
- Human oversight, testing, and review remain essential. AI augments reasoning and speed but does not replace engineering judgment.
- Quality and maintainability are goals treated with priority; AI contributes to these.

*Industry trends support this approach:*
according to the [JetBrains Developer Ecosystem 2025 survey published by *Golem.de*](https://www.golem.de/news/umfrage-unter-24-000-entwicklern-gesamtes-berufsfeld-befindet-sich-im-wandel-2510-188855.html), AI adoption is already pervasive and considered a core competency.


### License

This project is licensed under the terms of the MIT License.
See [LICENCE](LICENSE) for details.
