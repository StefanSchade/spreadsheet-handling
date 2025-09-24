#!/usr/bin/env bash
set -euo pipefail

# Usage: scripts/repo_snapshot.sh <REPO_ROOT> <TARGET_DIR> <OUTPUT_FILE>
if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <REPO_ROOT> <TARGET_DIR> <OUTPUT_FILE>"
  exit 1
fi

REPO_ROOT=$1
TARGET_DIR=$2
OUTFILE=$3

# robust absolut machen
abspath() {
  if command -v realpath >/dev/null 2>&1; then realpath -m -- "$1"
  else ( cd -- "$(dirname -- "$1")" && printf '%s/%s\n' "$(pwd)" "$(basename -- "$1")" ); fi
}
REPO_ROOT_ABS=$(abspath "$REPO_ROOT")
TARGET_DIR_ABS=$(abspath "$TARGET_DIR")
OUTFILE_ABS=$(abspath "$OUTFILE")

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
UTIL="${SCRIPT_DIR}/utils/concat_files.sh"

[[ -x "$UTIL" ]] || { echo "Utility not executable: $UTIL" >&2; exit 1; }
[[ -d "$REPO_ROOT_ABS" ]] || { echo "Repo root not found: $REPO_ROOT" >&2; exit 1; }
mkdir -p -- "$TARGET_DIR_ABS"

# folder based
EXTRA_NAME_EXCLUDES=( "tmp" )
# pattern based
EXTRA_PATH_EXCLUDES=(
  "$TARGET_DIR_ABS/*"
  # "$REPO_ROOT_ABS/tmp/*"   # optional
)

shopt -s globstar nullglob

# Optional: nur gewisse Dateitypen
FIND_FILTER=()

"$UTIL" "$REPO_ROOT_ABS" "$OUTFILE_ABS" \
  --exclude .git \
  --exclude .venv \
  $(for n in "${EXTRA_NAME_EXCLUDES[@]}"; do printf -- "--exclude %q " "$n"; done) \
  $(for p in "${EXTRA_PATH_EXCLUDES[@]}"; do printf -- "--exclude-path %q " "$p"; done) \
  -- \
  "${FIND_FILTER[@]}"

