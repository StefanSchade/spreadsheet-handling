#!/usr/bin/env bash
set -Eeuo pipefail

# --- resolve the absolute path of THIS script (follows symlinks too) ---
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPTS_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
REPO_ROOT="$(cd "$SCRIPTS_DIR/.." && pwd)"

# --- project-specific paths ---
PKG_ROOT="$REPO_ROOT/scripts"                       # where 'spreadsheet_handling' package lives
EXAMPLES="$PKG_ROOT/spreadsheet_handling/examples"
TMP_DIR="$PKG_ROOT/spreadsheet_handling/tmp"

mkdir -p "$TMP_DIR"
export PYTHONPATH="$PKG_ROOT"                       # so 'spreadsheet_handling' is importable

# --- run conversions ---
python3 -m spreadsheet_handling.cli.json2sheet \
  "$EXAMPLES/roundtrip_start.json" \
  -o "$TMP_DIR/tmp.xlsx" \
  --levels 3

python3 -m spreadsheet_handling.cli.sheet2json \
  "$TMP_DIR/tmp.xlsx" \
  -o "$TMP_DIR/tmp.json" \
  --levels 3

echo "Wrote: $TMP_DIR/tmp.xlsx and $TMP_DIR/tmp.json"

