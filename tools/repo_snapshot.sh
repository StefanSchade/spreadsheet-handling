#!/usr/bin/env bash
set -euo pipefail

# Usage: tools/repo_snapshot.sh <REPO_ROOT> <TARGET_DIR> <OUTPUT_FILE>
# Curates excludes and delegates to concat_files_core.sh

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <REPO_ROOT> <TARGET_DIR> <OUTPUT_FILE>"
  exit 1
fi

REPO_ROOT=$1
TARGET_DIR=$2
OUTFILE=$3

# Small portable abspath
abspath() {
  if command -v realpath >/dev/null 2>&1; then
    realpath -m -- "$1"
  else
    ( cd -- "$(dirname -- "$1")" && printf '%s/%s\n' "$(pwd)" "$(basename -- "$1")" )
  fi
}

ROOT_ABS=$(abspath "$REPO_ROOT")
TARGET_ABS=$(abspath "$TARGET_DIR")
OUTFILE_ABS=$(abspath "$OUTFILE")

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CORE="${SCRIPT_DIR}/concat_files_core.sh"
[[ -x "$CORE" ]] || { echo "Missing or non-executable: $CORE" >&2; exit 1; }

mkdir -p -- "$TARGET_ABS"

# Curated blacklists (compact & explicit)

# 1) Directory name prunes (applies anywhere in tree)
EX_DIRS=(
  ".git" ".venv" ".venv_win" "__pycache__" ".mypy_cache" ".pytest_cache" ".ruff_cache"
  ".idea" ".vscode" "node_modules" "dist" "build" "tmp" "lib" "lib64" "bin"
  "dist" "tmp" "target" "output"
)

# 2) Path globs (absolute, include the target dir to avoid recursion)
EX_PATHS=(
  "$TARGET_ABS/*"
)

# 3) File extensions to exclude (binary/heavy assets)
EX_EXTS=(
  "png" "jpg" "jpeg" "gif" "svg" "pdf"
  "xlsx" "xls" "xlsm" "xlsb"
  "doc" "docx" "ppt" "pptx" "zip" "tar" "gz" "bz2" "xz"
  "ipynb" "so" "pyc" "pyo" "rst" "csv" "log"
)

# Build flag arrays
flags=()
for d in "${EX_DIRS[@]}";  do flags+=( --exclude-dir "$d" ); done
for p in "${EX_PATHS[@]}"; do flags+=( --exclude-path "$p" ); done
for e in "${EX_EXTS[@]}";  do flags+=( --exclude-ext "$e" ); done

# Delegate (you can add extra find filters after --, e.g. -name '*.py' -o -name 'Makefile')
"$CORE" "$ROOT_ABS" "$OUTFILE_ABS" \
  "${flags[@]}" \
  -- \
#    in case a whitelist is wanted
#    \( -name '*.py' -o -name '*.yml' -o -name '*.yaml' -o -name 'Makefile' -o -name '*.sh' \)
