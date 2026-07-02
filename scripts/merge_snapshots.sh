#!/usr/bin/env bash
# Merge the two smallest .txt files in TARGET_DIR until the file count
# is no greater than MAX_FILES.  Each merge produces a combined file whose
# name is <stem1>_and_<stem2>.txt and whose content has a clear seam header
# so an LLM can tell where one origin file ends and the next begins.
#
# Usage: merge_snapshots.sh <TARGET_DIR> <MAX_FILES>

set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <TARGET_DIR> <MAX_FILES>" >&2
    exit 1
fi

TARGET_DIR="${1%/}"
MAX_FILES="$2"

if [[ ! -d "$TARGET_DIR" ]]; then
    echo "merge_snapshots: directory not found: $TARGET_DIR" >&2
    exit 1
fi

if ! [[ "$MAX_FILES" =~ ^[1-9][0-9]*$ ]]; then
    echo "merge_snapshots: MAX_FILES must be a positive integer, got: $MAX_FILES" >&2
    exit 1
fi

seam_header() {
    local a="$1" b="$2"
    printf '================================================================================\n'
    printf '== MERGED: %s  +  %s\n' "$a" "$b"
    printf '================================================================================\n\n'
}

section_header() {
    local f="$1"
    printf '================================================================================\n'
    printf '== BEGIN: %s\n' "$f"
    printf '================================================================================\n\n'
}

postprocess_file() {
    local file="$1"
    local raw unnumbered numbered
    raw=$(mktemp)
    unnumbered=$(mktemp)
    numbered=$(mktemp)

    cp -- "$file" "$raw"

    awk '
        {
            lines[NR] = $0
            if ($0 ~ /^==== File: .* ====$/) {
                path = $0
                sub(/^==== File: /, "", path)
                sub(/ ====$/, "", path)
                starts[++marker_count] = NR
                paths[marker_count] = path
            }
        }
        END {
            if (marker_count > 0) {
                toc_offset = marker_count + 5
                print "================================================================================"
                print "== Inhaltsverzeichnis"
                print "================================================================================"
                print ""
                for (i = 1; i <= marker_count; i++) {
                    printf "%06d | %s\n", starts[i] + toc_offset, paths[i]
                }
                print ""
            }
            for (i = 1; i <= NR; i++) {
                print lines[i]
            }
        }
    ' "$raw" > "$unnumbered"

    awk '{ printf "%06d | %s\n", NR, $0 }' "$unnumbered" > "$numbered"
    mv -- "$numbered" "$file"
    rm -f -- "$raw" "$unnumbered"
}

# Running counter for fallback names when the combined stem would exceed 200 chars.
_MERGE_SEQ=0

merge_two() {
    local f1="$1" f2="$2"
    local stem1 stem2 candidate merged
    stem1=$(basename "$f1" .txt)
    stem2=$(basename "$f2" .txt)
    candidate="${stem1}_and_${stem2}"

    if (( ${#candidate} > 200 )); then
        _MERGE_SEQ=$(( _MERGE_SEQ + 1 ))
        merged="$TARGET_DIR/merged_$(printf '%03d' "$_MERGE_SEQ").txt"
    else
        merged="$TARGET_DIR/${candidate}.txt"
    fi

    {
        seam_header "$(basename "$f1")" "$(basename "$f2")"
        section_header "$(basename "$f1")"
        cat "$f1"
        printf '\n\n'
        section_header "$(basename "$f2")"
        cat "$f2"
    } > "$merged"

    rm -- "$f1" "$f2"
    echo "  merged: $(basename "$f1") + $(basename "$f2") -> $(basename "$merged")"
}

while true; do
    mapfile -d '' files < <(find "$TARGET_DIR" -maxdepth 1 -name '*.txt' ! -name 'project_memory.txt' -print0)
    count="${#files[@]}"

    if (( count <= MAX_FILES )); then
        echo "merge_snapshots: $count files <= $MAX_FILES target, done."
        break
    fi

    # Sort by size ascending; pick the two smallest.
    mapfile -d '' sorted < <(
        printf '%s\0' "${files[@]}" | xargs -0 du -b | sort -k1,1n | cut -f2- | tr '\n' '\0'
    )

    merge_two "${sorted[0]}" "${sorted[1]}"
done
# Postprocess final files after all merges.
mapfile -d '' final_files < <(find "$TARGET_DIR" -maxdepth 1 -name '*.txt' -print0)
for merged in "${final_files[@]}"; do
    postprocess_file "$merged"
done
