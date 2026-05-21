#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-"$ROOT/build/pages"}"
# Sibling output directory that holds the root navigation page for the Pages
# artifact repository. Separated from the core subtree so the release
# workflow can copy this single file to the Pages repo root without
# entangling it with the rsync of `versions/<tag>/core/`.
ROOT_OUT_DIR="${2:-"$ROOT/build/pages-root"}"

VER="$(git -C "$ROOT" describe --tags --always --dirty 2>/dev/null || echo DEV-SNAPSHOT)"
REV="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo local)"
BUILD_DATE="$(date -Iseconds)"

PROJECT_URL="https://github.com/StefanSchade/spreadsheet-handling"
DEMO_URL="https://github.com/StefanSchade/spreadsheet-handling-demo"
PAGES_URL="https://stefanschade.github.io/spreadsheet-handling-pages/"

render_doc() {
  local src="$1"
  local out_dir="$2"

  mkdir -p "$out_dir"
  asciidoctor \
    -r asciidoctor-plantuml \
    -a project-name="spreadsheet-handling" \
    -a project-url="$PROJECT_URL" \
    -a demo-url="$DEMO_URL" \
    -a pages-url="$PAGES_URL" \
    -a project-version="$VER" \
    -a build-rev="$REV" \
    -a build-date="$BUILD_DATE" \
    -D "$out_dir" \
    -o index.html \
    "$ROOT/$src"
  echo "  $src -> $out_dir/index.html"
}

rm -rf "$OUT_DIR" "$ROOT_OUT_DIR"
mkdir -p "$OUT_DIR" "$ROOT_OUT_DIR"

# Core subtree (published as versions/<tag>/core/ and latest/core/).
render_doc "docs/pages/index.adoc"                  "$OUT_DIR"
render_doc "docs/user_guide/user_guide.adoc"        "$OUT_DIR/user-guide"
render_doc "docs/release_notes/release_notes.adoc"  "$OUT_DIR/release-notes"

# Root navigation page (published at the Pages repo root).
render_doc "docs/pages/root_index.adoc"             "$ROOT_OUT_DIR"
