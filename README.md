# Spreadsheet Handling

**Spreadsheet Handling** is a Python toolkit for packing/unpacking and orchestrating tabular data.  
It converts between JSON, CSV, and Excel (XLSX/ODS) while preserving relationships such as foreign keys, indexes, and hierarchies.  
The goal is to make complex spreadsheet models easier to validate, transform, and round-trip into structured formats.

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

### Pack JSON into Excel:

```bash
sheets-pack examples/roundtrip_start.json -o demo.xlsx --levels 3
```

### Unpack Excel back into JSON:

```bash
sheets-unpack demo.xlsx -o demo_out --levels 3
```

### Run full test suite:

```bash
make test
```

### License

This project is licensed under the terms of the MIT License.
See [LICENCE](LICENSE) for details.


