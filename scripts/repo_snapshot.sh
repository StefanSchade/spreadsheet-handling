#!/usr/bin/env bash
set -euo pipefail

# Usage: scripts/repo_snapshot.sh <REPO_ROOT> <OUTPUT_FILE>
if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <REPO_ROOT> <OUTPUT_FILE>"
  exit 1
fi

REPO_ROOT=$1
OUTFILE=$2

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
UTIL="${SCRIPT_DIR}/utils/concat_files.sh"

[[ -x "$UTIL" ]] || { echo "Utility not executable: $UTIL" >&2; exit 1; }
[[ -d "$REPO_ROOT" ]] || { echo "Repo root not found: $REPO_ROOT" >&2; exit 1; }

# Hier kannst du repo-spezifische Zusatz-Excludes angeben (optional):
# EXTRA_NAME_EXCLUDES=( "node_modules" ".mypy_cache" )
EXTRA_NAME_EXCLUDES=()
EXTRA_PATH_EXCLUDES=()

# Beispiel: nur bestimmte Dateitypen aufnehmen – kommentiere aus wenn gewünscht
# FIND_FILTER=( -name "*.adoc" -o -name "*.md" )
FIND_FILTER=()

# Aufruf Utility: .git und .venv immer raus; plus evtl. Extras
# -- sichert, dass alles nach dem Trenner 1:1 bei find landet (z. B. -maxdepth etc.)
"$UTIL" "$REPO_ROOT" "$OUTFILE" \
  --exclude .git \
  --exclude .venv \
  $(for n in "${EXTRA_NAME_EXCLUDES[@]}"; do printf -- "--exclude %q " "$n"; done) \
  $(for p in "${EXTRA_PATH_EXCLUDES[@]}"; do printf -- "--exclude-path %q " "$p"; done) \
  -- \
  "${FIND_FILTER[@]}"

