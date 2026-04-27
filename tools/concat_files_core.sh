#!/usr/bin/env bash
set -euo pipefail

# Concatenate UTF-8 compatible text files under ROOT into OUTFILE,
# excluding via repeated flags:
#   --exclude-dir NAME        (prunes by directory name)
#   --exclude-path GLOB       (prunes by full path glob)
#   --exclude-ext EXT         (blacklist by file extension, e.g. 'png')
#   --                        (separator; anything after goes to `find`)

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <ROOT> <OUTFILE> [--exclude-dir NAME ...] [--exclude-path GLOB ...] [--exclude-ext EXT ...] [--] [find-args...]"
  exit 1
fi

ROOT=$1; OUTFILE=$2; shift 2

EX_DIRS=()
EX_PATHS=()
EX_EXTS=()
FIND_OPTS=()

# Parse flags (repeatable)
while (( $# )); do
  case "${1:-}" in
    --exclude-dir)  shift; EX_DIRS+=( "${1:?--exclude-dir needs a value}" ) ;;
    --exclude-path) shift; EX_PATHS+=( "${1:?--exclude-path needs a value}" ) ;;
    --exclude-ext)  shift; EX_EXTS+=( "${1:?--exclude-ext needs a value}" ) ;;
    --) shift; while (( $# )); do FIND_OPTS+=( "$1" ); shift; done; break ;;
    *)  FIND_OPTS+=( "$1" ) ;;
  esac
  shift || true
done

# NUL-safe, robust concatenation
: > "$OUTFILE"

# Build prune expressions
PRUNE_DIRS=()
if (( ${#EX_DIRS[@]} )); then
  PRUNE_DIRS+=( -type d '(' )
  for i in "${!EX_DIRS[@]}"; do
    PRUNE_DIRS+=( -name "${EX_DIRS[$i]}" )
    (( i < ${#EX_DIRS[@]} - 1 )) && PRUNE_DIRS+=( -o )
  done
  PRUNE_DIRS+=( ')' -prune -o )
fi

# Normalize path excludes: if "X/*" also prune "X"; if "X" also prune "X/*"
NORMALIZED_PATHS=()
for p in "${EX_PATHS[@]}"; do
  NORMALIZED_PATHS+=( "$p" )
  if [[ "$p" == */\* ]]; then
    NORMALIZED_PATHS+=( "${p%/\*}" )
  else
    NORMALIZED_PATHS+=( "$p/*" )
  fi
done

PRUNE_PATHS=()
if (( ${#NORMALIZED_PATHS[@]} )); then
  PRUNE_PATHS+=( '(' )
  for i in "${!NORMALIZED_PATHS[@]}"; do
    PRUNE_PATHS+=( -path "${NORMALIZED_PATHS[$i]}" )
    (( i < ${#NORMALIZED_PATHS[@]} - 1 )) && PRUNE_PATHS+=( -o )
  done
  PRUNE_PATHS+=( ')' -prune -o )
fi

# Build extension blacklist
PRUNE_EXTS=()
if (( ${#EX_EXTS[@]} )); then
  PRUNE_EXTS+=( '(' )
  for i in "${!EX_EXTS[@]}"; do
    PRUNE_EXTS+=( -name "*.${EX_EXTS[$i]}" )
    (( i < ${#EX_EXTS[@]} - 1 )) && PRUNE_EXTS+=( -o )
  done
  PRUNE_EXTS+=( ')' -prune -o )
fi

# Always avoid re-reading the output file
PRUNE_OUTFILE=( -path "$OUTFILE" -prune -o )

find "$ROOT" \
  "${FIND_OPTS[@]}" \
  "${PRUNE_DIRS[@]}" \
  "${PRUNE_PATHS[@]}" \
  "${PRUNE_EXTS[@]}" \
  "${PRUNE_OUTFILE[@]}" \
  -type f -print0 \
| while IFS= read -r -d '' FILE; do
    # Keep blacklist, but still ensure UTF-8 compatible text.
    # `file` reports pure ASCII files as us-ascii; those are valid UTF-8 too.
    ENCODING=$(file --mime-encoding "$FILE" | awk '{print $NF}')
    if [[ "$ENCODING" == "utf-8" || "$ENCODING" == "us-ascii" ]]; then
      {
        printf '==== File: %s ====\n\n' "$FILE"
        cat -- "$FILE"
        printf '\n'
      } >> "$OUTFILE"
    fi
  done

echo "Snapshot written to $OUTFILE"
