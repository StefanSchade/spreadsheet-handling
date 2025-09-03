#!/usr/bin/env bash
set -euo pipefail

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
  echo "Options (vor beliebigen find-Args möglich, mehrfach nutzbar):"
  echo "  --exclude NAME            # Verzeichnisname global ignorieren (z.B. node_modules)"
  echo "  --exclude-path GLOB       # Pfad-Glob, z.B. '*/build/*' (für -path)"
  echo "  --exclude-file FILE       # Datei mit Zeilen: NAME  oder  PATH:GLOB"
  echo "  --no-default-excludes     # .git und .venv NICHT automatisch ausschließen"
  echo "  --                        # Trenner; alles danach geht 1:1 an find"
  exit 1
fi

DIRECTORY=$1
OUTPUT_FILE=$2
shift 2

# ---------------------------------
# CLI-Parsing
# ---------------------------------
NAME_EXCLUDES=()
PATH_EXCLUDES=()
FIND_OPTIONS=()

read_exclude_file() {
  local f="$1"
  [[ -f "$f" ]] || { echo "Exclude file not found: $f" >&2; exit 1; }
  while IFS= read -r line || [[ -n "$line" ]]; do
    # Kommentare und Leerzeilen überspringen
    [[ -z "${line// }" ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    # Optionales Format: PATH:<glob>  oder  NAME:<dir>
    if [[ "$line" == PATH:* ]]; then
      PATH_EXCLUDES+=( "${line#PATH:}" )
    elif [[ "$line" == NAME:* ]]; then
      NAME_EXCLUDES+=( "${line#NAME:}" )
    else
      # Heuristik: alles ohne Slash als NAME, sonst als PATH-Glob
      if [[ "$line" == */* ]]; then
        PATH_EXCLUDES+=( "$line" )
      else
        NAME_EXCLUDES+=( "$line" )
      fi
    fi
  done < "$f"
}

while (( $# )); do
  case "${1:-}" in
    --exclude)
      shift
      [[ $# -gt 0 ]] || { echo "--exclude braucht ein Argument" >&2; exit 1; }
      NAME_EXCLUDES+=( "$1" )
      ;;
    --exclude-path)
      shift
      [[ $# -gt 0 ]] || { echo "--exclude-path braucht ein Argument" >&2; exit 1; }
      PATH_EXCLUDES+=( "$1" )
      ;;
    --exclude-file)
      shift
      [[ $# -gt 0 ]] || { echo "--exclude-file braucht ein Argument" >&2; exit 1; }
      read_exclude_file "$1"
      ;;
    --no-default-excludes)
      USE_DEFAULT_EXCLUDES=0
      ;;
    --)
      shift
      # Rest unverändert an find weiterreichen
      while (( $# )); do FIND_OPTIONS+=( "$1" ); shift; done
      break
      ;;
    *)
      # Unbekannt → direkt an find weitergeben (Reihenfolge bleibt erhalten)
      FIND_OPTIONS+=( "$1" )
      ;;
  esac
  shift || true
done

# Defaults anhängen (falls nicht deaktiviert)
if [[ "$USE_DEFAULT_EXCLUDES" -eq 1 ]]; then
  NAME_EXCLUDES=( "${DEFAULT_NAME_EXCLUDES[@]}" "${NAME_EXCLUDES[@]}" )
fi

# ---------------------------------
# Checks & Vorbereitung
# ---------------------------------
if [[ ! -d "$DIRECTORY" ]]; then
  echo "Error: Directory '$DIRECTORY' does not exist." >&2
  exit 1
fi
: > "$OUTPUT_FILE"

# ---------------------------------
# find-Ausdrücke bauen
# ---------------------------------
# 1) Name-basierte Verzeichnis-Excludes: -type d \( -name X -o -name Y \) -prune -false -o
PRUNE_NAME_EXPR=()
if (( ${#NAME_EXCLUDES[@]} )); then
  PRUNE_NAME_EXPR+=( -type d '(' )
  for i in "${!NAME_EXCLUDES[@]}"; do
    PRUNE_NAME_EXPR+=( -name "${NAME_EXCLUDES[$i]}" )
    (( i < ${#NAME_EXCLUDES[@]} - 1 )) && PRUNE_NAME_EXPR+=( -o )
  done
  PRUNE_NAME_EXPR+=( ')' -prune -false -o )
fi

# 2) Pfad-Globs (können auch Dateien treffen): \( -path '*/build/*' -o -path '*/dist/*' \) -prune -false -o
PRUNE_PATH_EXPR=()
if (( ${#PATH_EXCLUDES[@]} )); then
  PRUNE_PATH_EXPR+=( '(' )
  for i in "${!PATH_EXCLUDES[@]}"; do
    PRUNE_PATH_EXPR+=( -path "${PATH_EXCLUDES[$i]}" )
    (( i < ${#PATH_EXCLUDES[@]} - 1 )) && PRUNE_PATH_EXPR+=( -o )
  done
  PRUNE_PATH_EXPR+=( ')' -prune -false -o )
fi

# ---------------------------------
# find & Verarbeitung
# ---------------------------------
# Reihenfolge: Nutzer-Filter (FIND_OPTIONS) → feste PRUNEs → -type f
find "$DIRECTORY" \
  "${FIND_OPTIONS[@]}" \
  "${PRUNE_NAME_EXPR[@]}" \
  "${PRUNE_PATH_EXPR[@]}" \
  -type f \
| while IFS= read -r FILE; do
    if file --mime-encoding "$FILE" | grep -q 'utf-8'; then
      echo "Processing $FILE"
      {
        echo "==== File: $FILE ===="
        echo
        cat "$FILE"
        echo
      } >> "$OUTPUT_FILE"
    else
      echo "Skipping non-UTF-8 file: $FILE"
    fi
  done

echo "All files concatenated into $OUTPUT_FILE"

