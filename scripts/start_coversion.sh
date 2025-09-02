#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

export PYTHONPATH=./

python3 -m spreadsheet_handling.cli.json2sheet \
  spreadsheet_handling/examples/roundtrip_start.json \
  -o spreadsheet_handling/out.xlsx \
  --levels 3

python3 -m spreadsheet_handling.cli.sheet2json \
  spreadsheet_handling/out.xlsx \
  -o spreadsheet_handling/out.json \
  --levels 3

