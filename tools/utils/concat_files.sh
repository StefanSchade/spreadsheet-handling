#!/usr/bin/env bash
set -euo pipefail

echo "Generating file snapshot"

# ---------------------------------
# Defaults
# ---------------------------------
DEFAULT_NAME_EXCLUDES=( ".git" ".venv" )
USE_DEFAULT_EXCLUDES=1

# ---------------------------------
# Usage
# ---------------------------------
if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <DIRECTORY> <OUTPUT_FILE> [options & find-args...]"
  echo
  echo "Options (mehrfach nutzbar, Reihenfolge egal):"
  echo "  --exclude NAME            # Verzeichnisname ignorieren (z. B. node_modules)"
  echo "  --exclude-path GLOB       # Pfad-Glob, z. B. '*/build/*' (für -path)"
  echo "  --exclude-file FILE       # Datei, 1 Muster/Z.: NAME:<dir> | PATH:<glob> | autodetect"
  echo "  --no-default-excludes     # .git und .venv NICHT automatisch ausschließen"
  echo "  --                        # Trenner; alles danach geht 1:1 an find"
  exit 1
fi

DIRECTORY=$1
OUTPUT_FILE=$2
shift 2

# --- kleine Helfer für absolute Pfade ---
_abspath() {
  # realpath, falls vorhanden
  if command -v realpath >/dev/null 2>&1; then
    realpath -m -- "$1"
  else
    # Fallback: cd + pwd
    ( cd -- "$(dirname -- "$1")" && printf '%s/%s\n' "$(pwd)" "$(basename -- "$1")" )
  fi
}

DIRECTORY_ABS=$(_abspath "$DIRECTORY")
OUTPUT_FILE_ABS=$(_abspath "$OUTPUT_FILE")
OUTPUT_DIR_ABS=$(_abspath "$(dirname -- "$OUTPUT_FILE")")

NAME_EXCLUDES=()
PATH_EXCLUDES=()
FIND_OPTIONS=()

read_exclude_file() { # ... (unverändert wie bei dir) ...
  local f="$1"
  [[ -f "$f" ]] || { echo "Exclude file not found: $f" >&2; exit 1; }
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line// }" ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ "$line" == PATH:* ]]; then
      PATH_EXCLUDES+=( "${line#PATH:}" )
    elif [[ "$line" == NAME:* ]]; then
      NAME_EXCLUDES+=( "${line#NAME:}" )
    else
      if [[ "$line" == */* ]]; then PATH_EXCLUDES+=( "$line" ); else NAME_EXCLUDES+=( "$line" ); fi
    fi
  done < "$f"
}

while (( $# )); do
  case "${1:-}" in
    --exclude)        shift; [[ $# -gt 0 ]] || { echo "--exclude braucht ein Argument" >&2; exit 1; }; NAME_EXCLUDES+=( "$1" ) ;;
    --exclude-path)   shift; [[ $# -gt 0 ]] || { echo "--exclude-path braucht ein Argument" >&2; exit 1; }; PATH_EXCLUDES+=( "$1" ) ;;
    --exclude-file)   shift; [[ $# -gt 0 ]] || { echo "--exclude-file braucht ein Argument" >&2; exit 1; }; read_exclude_file "$1" ;;
    --no-default-excludes) USE_DEFAULT_EXCLUDES=0 ;;
    --) shift; while (( $# )); do FIND_OPTIONS+=( "$1" ); shift; done; break ;;
    *)  FIND_OPTIONS+=( "$1" ) ;;
  esac
  shift || true
done

if [[ "$USE_DEFAULT_EXCLUDES" -eq 1 ]]; then
  NAME_EXCLUDES=( "${DEFAULT_NAME_EXCLUDES[@]}" "${NAME_EXCLUDES[@]}" )
fi

[[ -d "$DIRECTORY_ABS" ]] || { echo "Error: Directory '$DIRECTORY' does not exist." >&2; exit 1; }
: > "$OUTPUT_FILE_ABS"

# ----------------- PRUNES bauen -----------------
PRUNE_NAME_EXPR=()
if (( ${#NAME_EXCLUDES[@]} )); then
  PRUNE_NAME_EXPR+=( -type d '(' )
  for i in "${!NAME_EXCLUDES[@]}"; do
    PRUNE_NAME_EXPR+=( -name "${NAME_EXCLUDES[$i]}" )
    (( i < ${#NAME_EXCLUDES[@]} - 1 )) && PRUNE_NAME_EXPR+=( -o )
  done
  PRUNE_NAME_EXPR+=( ')' -prune -false -o )
fi

PRUNE_PATH_EXPR=()
if (( ${#PATH_EXCLUDES[@]} )); then
  PRUNE_PATH_EXPR+=( '(' )
  for i in "${!PATH_EXCLUDES[@]}"; do
    PRUNE_PATH_EXPR+=( -path "${PATH_EXCLUDES[$i]}" )
    (( i < ${#PATH_EXCLUDES[@]} - 1 )) && PRUNE_PATH_EXPR+=( -o )
  done
  PRUNE_PATH_EXPR+=( ')' -prune -false -o )
fi

PRUNE_OUTFILE_EXPR=( -path "$OUTPUT_FILE_ABS" -prune -o )


# Optional: auch das Output-Verzeichnis prunen (meist nicht nötig, kann aber Build-Verzeichnisse sauber halten)
# PRUNE_OUTDIR_EXPR=( -path "$OUTPUT_DIR_ABS/*" -prune -false -o )

# ----------------- find & Verarbeitung -----------------
# Tipp: robust gegen Spaces mit -print0
find "$DIRECTORY_ABS" \
  "${FIND_OPTIONS[@]}" \
  "${PRUNE_NAME_EXPR[@]}" \
  "${PRUNE_PATH_EXPR[@]}" \
  "${PRUNE_OUTFILE_EXPR[@]}" \
  -type f -print0 \
| while IFS= read -r -d '' FILE; do
    if file --mime-encoding "$FILE" | grep -q 'utf-8'; then
      echo "Processing $FILE"
      {
        echo "==== File: $FILE ===="
        echo
        cat "$FILE"
        echo
      } >> "$OUTPUT_FILE_ABS"
    else
      echo "Skipping non-UTF-8 file: $FILE"
    fi
  done

echo "All files concatenated into $OUTPUT_FILE_ABS"

