#!/usr/bin/env bash
set -euo pipefail

# Usage: tools/repo_snapshot_multi.sh <REPO_ROOT> <TARGET_DIR>
# Produces focused snapshot files per section in TARGET_DIR:
#   docs_<subdir>.txt, src_<subdir>.txt, src_toplevel.txt,
#   tests_<subdir>.txt, tree.txt, repo_infrastructure.txt, loc.txt

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <REPO_ROOT> <TARGET_DIR>" >&2
  exit 1
fi

REPO_ROOT="${1%/}/"
TARGET_DIR="$2"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CORE="${SCRIPT_DIR}/concat_files_core.sh"
[[ -x "$CORE" ]] || { echo "Missing or non-executable: $CORE" >&2; exit 1; }

rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"

# Append a single UTF-8 file with the standard ==== File: ... ==== header.
append_file() {
    local f="$1" out="$2"
    local enc
    enc=$(file --mime-encoding "$f" 2>/dev/null | awk '{print $NF}')
    [[ "$enc" == "utf-8" || "$enc" == "us-ascii" ]] || return 0
    printf '==== File: %s ====\n\n' "$f" >> "$out"
    cat -- "$f" >> "$out"
    printf '\n' >> "$out"
}

# Thin wrapper: suppresses concat_files_core.sh's progress line.
run_core() {
    bash "$CORE" "$@" >/dev/null
}

# Common directory and extension blacklists (mirrors repo_snapshot.sh).
EXCL=(
    --exclude-dir .git       --exclude-dir .venv      --exclude-dir .venv_win
    --exclude-dir __pycache__ --exclude-dir .mypy_cache --exclude-dir .pytest_cache
    --exclude-dir .ruff_cache --exclude-dir .idea      --exclude-dir .vscode
    --exclude-dir node_modules --exclude-dir dist      --exclude-dir build
    --exclude-dir tmp        --exclude-dir lib         --exclude-dir lib64
    --exclude-dir bin        --exclude-dir target      --exclude-dir output
    --exclude-dir cold_storage --exclude-dir warm_storage_phase3
    --exclude-ext pyc  --exclude-ext pyo  --exclude-ext pdf
    --exclude-ext png  --exclude-ext jpg  --exclude-ext jpeg
    --exclude-ext gif  --exclude-ext svg
    --exclude-ext xlsx --exclude-ext xls  --exclude-ext xlsm --exclude-ext xlsb
    --exclude-ext doc  --exclude-ext docx --exclude-ext ppt  --exclude-ext pptx
    --exclude-ext zip  --exclude-ext tar  --exclude-ext gz   --exclude-ext bz2
    --exclude-ext xz   --exclude-ext so   --exclude-ext ipynb
    --exclude-ext rst  --exclude-ext csv  --exclude-ext log
    --exclude-ext ods
)

# Extension whitelists per section type.
DOC_INCL=(
    --include-ext adoc --include-ext md   --include-ext txt
    --include-ext json --include-ext yaml --include-ext yml
)
PY_INCL=(
    --include-ext py   --include-ext yaml --include-ext yml
    --include-ext json --include-ext toml
)
INFRA_INCL=(
    --include-ext sh   --include-ext py   --include-ext yml
    --include-ext yaml --include-ext toml --include-ext md
    --include-ext adoc --include-ext txt
)

PROJECT_MEMORY_INCL=(
    --include-ext adoc --include-ext json --include-ext yaml
    --include-ext yml  --include-ext py   --include-ext txt
)

# Returns 0 (true) when a directory name should be skipped in iteration.
# Mirrors the --exclude-dir list in EXCL so that no snapshot file is created
# for excluded dirs (their contents would be empty anyway, but we avoid the noise).
skip_dir() {
    case "$1" in
        .git|.venv|.venv_win|__pycache__|.mypy_cache|.pytest_cache|.ruff_cache) return 0 ;;
        .idea|.vscode|node_modules|dist|build|tmp|lib|lib64|bin|target|output)   return 0 ;;
        cold_storage|warm_storage_phase3) return 0 ;;
    esac
    return 1
}

echo "Building multi-snapshots in $TARGET_DIR ..."

# ---- docs/ subdirs -------------------------------------------------------
for dir in "${REPO_ROOT}docs/"*/; do
    [ -d "$dir" ] || continue
    name=$(basename "$dir")
    skip_dir "$name" && continue
    out="$TARGET_DIR/docs_${name}.txt"
    run_core "$dir" "$out" "${EXCL[@]}" "${DOC_INCL[@]}"
    if [ -s "$out" ]; then echo "  docs_${name}.txt"; else rm -f "$out"; fi
done

# ---- src/spreadsheet_handling/ subdirs -----------------------------------
SRC="${REPO_ROOT}src/spreadsheet_handling/"
for dir in "$SRC"*/; do
    [ -d "$dir" ] || continue
    name=$(basename "$dir")
    skip_dir "$name" && continue
    out="$TARGET_DIR/src_${name}.txt"
    run_core "$dir" "$out" "${EXCL[@]}" "${PY_INCL[@]}"
    if [ -s "$out" ]; then echo "  src_${name}.txt"; else rm -f "$out"; fi
done

# ---- src/spreadsheet_handling/ top-level .py files ----------------------
out="$TARGET_DIR/src_toplevel.txt"
: > "$out"
for f in "$SRC"*.py; do
    [ -f "$f" ] || continue
    append_file "$f" "$out"
done
if [ -s "$out" ]; then echo "  src_toplevel.txt"; else rm -f "$out"; fi

# ---- tests/ subdirs ------------------------------------------------------
for dir in "${REPO_ROOT}tests/"*/; do
    [ -d "$dir" ] || continue
    name=$(basename "$dir")
    skip_dir "$name" && continue
    out="$TARGET_DIR/tests_${name}.txt"
    run_core "$dir" "$out" "${EXCL[@]}" "${PY_INCL[@]}"
    if [ -s "$out" ]; then echo "  tests_${name}.txt"; else rm -f "$out"; fi
done

# ---- tree.txt ------------------------------------------------------------
if command -v tree >/dev/null 2>&1; then
    tree -L 3 "$REPO_ROOT" > "$TARGET_DIR/tree.txt"
    if [ -d "${REPO_ROOT}project_memory" ]; then
        {
            printf '\n'
            printf '=== project_memory subtree ===\n'
            tree -L 3 "${REPO_ROOT}project_memory"
        } >> "$TARGET_DIR/tree.txt"
    fi
    echo "  tree.txt"
else
    echo "WARNING: 'tree' not found — skipping tree.txt" >&2
fi

# ---- repo_infrastructure.txt --------------------------------------------
INFRA="$TARGET_DIR/repo_infrastructure.txt"
: > "$INFRA"

# Explicit top-level named files.
for f in Makefile pyproject.toml CLAUDE.md AGENT.md README.md pipeline.yml sheets.yaml; do
    fp="${REPO_ROOT}${f}"
    [ -f "$fp" ] || continue
    append_file "$fp" "$INFRA"
done

# Subdirectories with tooling and CI config.
_tmp=$(mktemp)
trap 'rm -f "$_tmp"' EXIT
for sub in scripts tools .github; do
    dir="${REPO_ROOT}${sub}/"
    [ -d "$dir" ] || continue
    run_core "$dir" "$_tmp" "${EXCL[@]}" "${INFRA_INCL[@]}"
    cat "$_tmp" >> "$INFRA"
done
echo "  repo_infrastructure.txt"

# ---- project_memory.txt --------------------------------------------------
PROJECT_MEMORY_ROOT="${REPO_ROOT}project_memory/"
if [ -d "$PROJECT_MEMORY_ROOT" ]; then
    out="$TARGET_DIR/project_memory.txt"
    run_core "$PROJECT_MEMORY_ROOT" "$out" \
        "${EXCL[@]}" \
        --exclude-dir staging \
        --exclude-dir tmp \
        --exclude-path "${PROJECT_MEMORY_ROOT}staging" \
        --exclude-path "${PROJECT_MEMORY_ROOT}staging/*" \
        --exclude-path "${PROJECT_MEMORY_ROOT}tmp" \
        --exclude-path "${PROJECT_MEMORY_ROOT}tmp/*" \
        --exclude-path "${PROJECT_MEMORY_ROOT}canonical/_meta.yaml" \
        --exclude-path "${PROJECT_MEMORY_ROOT}*/_meta.yaml" \
        --exclude-path "${REPO_ROOT}project_memory.ods" \
        "${PROJECT_MEMORY_INCL[@]}"
    if [ -s "$out" ]; then echo "  project_memory.txt"; else rm -f "$out"; fi
fi

# ---- loc.txt -------------------------------------------------------------
if command -v cloc >/dev/null 2>&1; then
    {
        echo "=== src/ + tests/ overall ==="
        cloc "${REPO_ROOT}src" "${REPO_ROOT}tests"
        echo ""
        echo "=== src/spreadsheet_handling/ subdirs ==="
        for dir in "$SRC"*/; do
            [ -d "$dir" ] || continue
            echo "--- src/$(basename "$dir") ---"
            cloc "$dir"
        done
        echo ""
        echo "=== tests/ subdirs ==="
        for dir in "${REPO_ROOT}tests/"*/; do
            [ -d "$dir" ] || continue
            echo "--- tests/$(basename "$dir") ---"
            cloc "$dir"
        done
    } > "$TARGET_DIR/loc.txt"
    echo "  loc.txt"
else
    echo "WARNING: 'cloc' not found — skipping loc.txt" >&2
fi

echo "Done."
