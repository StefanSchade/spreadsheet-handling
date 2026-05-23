#!/usr/bin/env bash
# pages_publish_check.sh -- Verify Pages publish output structure (read-only).
#
# Inspects a local checkout of `spreadsheet-handling-pages` and reports whether
# the expected files for a given core (and optionally demo) release tag are
# present in the published topology:
#
#   <pages>/index.html                                          (root nav page)
#   <pages>/.nojekyll                                           (Pages opt-out)
#   <pages>/versions/<core-tag>/core/index.html
#   <pages>/versions/<core-tag>/core/user-guide/index.html
#   <pages>/versions/<core-tag>/core/release-notes/index.html
#   <pages>/latest/core/{index,user-guide/index,release-notes/index}.html  (optional)
#   <pages>/versions/<demo-tag>/demo/slides/*.html              (optional)
#   <pages>/latest/demo/slides/*.html                           (optional)
#
# Usage:
#   pages_publish_check.sh --core-tag v0.1.0b6
#   pages_publish_check.sh --core-tag v0.1.0b6 --demo-tag v0.1.0b6-demo
#   pages_publish_check.sh --core-tag v0.1.0b6 --check-latest
#   pages_publish_check.sh --pages /path/to/pages --core-tag v0.1.0b6 \
#                          --demo-tag v0.1.0b6-demo --check-latest
#
# Env (alternative to flags):
#   PAGES_DIR   path to local pages checkout (default: try ../pages and
#               ../spreadsheet-handling-pages relative to $PWD)
#   CORE_TAG    e.g. v0.1.0b6
#   DEMO_TAG    e.g. v0.1.0b6-demo
#
# Read-only contract:
#   The script performs no git or filesystem-mutating operations. It only
#   reads the pages working tree. It does not assume the pages checkout is
#   up to date with the remote; `git -C <pages> pull --ff-only` is the
#   operator's responsibility before invoking the check.
#
# Per-section classification:
#   plausible  -- all expected files exist and are nonzero in size
#   partial    -- the section's parent directory exists but one or more
#                 expected files are missing or empty
#   missing    -- the section's parent directory does not exist at all
#
# Exit codes:
#   0   every checked section is plausible
#   1   at least one section is partial (some files missing)
#   2   at least one section is missing entirely
#   3   usage / setup error (pages dir not found, required arg absent, ...)

set -euo pipefail

# ------------------------------------------------------------
# Argument parsing
# ------------------------------------------------------------
pages_dir="${PAGES_DIR:-}"
core_tag="${CORE_TAG:-}"
demo_tag="${DEMO_TAG:-}"
check_latest=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pages)        pages_dir="${2:?--pages requires a path}"; shift 2 ;;
    --core-tag)     core_tag="${2:?--core-tag requires a value}"; shift 2 ;;
    --demo-tag)     demo_tag="${2:?--demo-tag requires a value}"; shift 2 ;;
    --check-latest) check_latest=1; shift ;;
    -h|--help)
      sed -n '2,40p' "$0"
      exit 0
      ;;
    *)
      printf 'pages_publish_check: unknown argument: %s\n' "$1" >&2
      exit 3
      ;;
  esac
done

# ------------------------------------------------------------
# Color helpers (only when stdout is a terminal)
# ------------------------------------------------------------
if [[ -t 1 ]]; then
  C_PASS="$(printf '\033[32m')"
  C_WARN="$(printf '\033[33m')"
  C_FAIL="$(printf '\033[31m')"
  C_DIM="$(printf '\033[2m')"
  C_RESET="$(printf '\033[0m')"
else
  C_PASS=""; C_WARN=""; C_FAIL=""; C_DIM=""; C_RESET=""
fi

pass()  { printf '  %sPASS%s   %s\n' "$C_PASS" "$C_RESET" "$1"; }
warn()  { printf '  %sWARN%s   %s\n' "$C_WARN" "$C_RESET" "$1"; }
fail()  { printf '  %sFAIL%s   %s\n' "$C_FAIL" "$C_RESET" "$1"; }
skip()  { printf '  %sSKIP%s   %s\n' "$C_DIM"  "$C_RESET" "$1"; }

# ------------------------------------------------------------
# Resolve pages_dir
# ------------------------------------------------------------
if [[ -z "$pages_dir" ]]; then
  for candidate in ../pages ../spreadsheet-handling-pages; do
    if [[ -d "$candidate" && -e "$candidate/.nojekyll" ]]; then
      pages_dir="$candidate"
      break
    fi
  done
fi

if [[ -z "$pages_dir" ]]; then
  printf 'pages_publish_check: pages checkout not found.\n' >&2
  printf '  Pass --pages PATH, set PAGES_DIR=PATH, or run from a workspace\n' >&2
  printf '  where ../pages or ../spreadsheet-handling-pages exists.\n' >&2
  exit 3
fi

if [[ ! -d "$pages_dir" ]]; then
  printf 'pages_publish_check: pages directory does not exist: %s\n' "$pages_dir" >&2
  exit 3
fi

# Normalize for display only
pages_abs="$(cd "$pages_dir" && pwd)"

if [[ -z "$core_tag" ]]; then
  printf 'pages_publish_check: --core-tag is required (e.g. v0.1.0b6).\n' >&2
  printf '  Alternatively set CORE_TAG in the environment.\n' >&2
  exit 3
fi

# ------------------------------------------------------------
# Per-section state (each section ends in plausible/partial/missing)
# ------------------------------------------------------------
plausible_count=0
partial_count=0
missing_count=0

# check_file PATH LABEL  -> returns 0 if nonzero file exists, 1 otherwise
check_file() {
  local path="$1" label="$2"
  if [[ -f "$path" && -s "$path" ]]; then
    pass "$label"
    return 0
  elif [[ -f "$path" ]]; then
    fail "$label (present but empty)"
    return 1
  else
    fail "$label (missing)"
    return 1
  fi
}

# Run a section. Caller defines a list of expected files; the section's
# parent directory is taken from the first expected file. The section is
# classified missing/partial/plausible based on per-file results.
run_section() {
  local section_label="$1"; shift
  local parent_dir="$1"; shift
  # Remaining args are FILE LABEL FILE LABEL ... pairs.

  printf '\n%s\n' "$section_label"

  if [[ ! -d "$parent_dir" ]]; then
    fail "directory does not exist: ${parent_dir#$pages_abs/}"
    printf '  -> %smissing%s\n' "$C_FAIL" "$C_RESET"
    missing_count=$((missing_count + 1))
    return
  fi

  local fail_inside=0
  while [[ $# -gt 0 ]]; do
    if ! check_file "$1" "$2"; then
      fail_inside=$((fail_inside + 1))
    fi
    shift 2
  done

  if [[ "$fail_inside" -eq 0 ]]; then
    printf '  -> %splausible%s\n' "$C_PASS" "$C_RESET"
    plausible_count=$((plausible_count + 1))
  else
    printf '  -> %spartial%s (%d expected file(s) missing or empty)\n' \
      "$C_WARN" "$C_RESET" "$fail_inside"
    partial_count=$((partial_count + 1))
  fi
}

# ------------------------------------------------------------
# Run sections
# ------------------------------------------------------------
printf 'pages_publish_check: pages=%s\n' "$pages_abs"
printf '                     core_tag=%s' "$core_tag"
[[ -n "$demo_tag" ]] && printf ', demo_tag=%s' "$demo_tag"
[[ "$check_latest" -eq 1 ]] && printf ', check-latest'
printf '\n'

# Section: pages root invariants
printf '\nPages root invariants\n'
root_fails=0
check_file "$pages_abs/index.html" "index.html"             || root_fails=$((root_fails + 1))
if [[ -f "$pages_abs/.nojekyll" ]]; then
  pass ".nojekyll"
else
  fail ".nojekyll (missing)"
  root_fails=$((root_fails + 1))
fi
if [[ "$root_fails" -eq 0 ]]; then
  printf '  -> %splausible%s\n' "$C_PASS" "$C_RESET"
  plausible_count=$((plausible_count + 1))
else
  printf '  -> %spartial%s (%d expected file(s) missing)\n' \
    "$C_WARN" "$C_RESET" "$root_fails"
  partial_count=$((partial_count + 1))
fi

# Section: core versioned publish
core_versioned="$pages_abs/versions/$core_tag/core"
run_section "Core versioned publish (versions/$core_tag/core/)" \
  "$core_versioned" \
  "$core_versioned/index.html"               "index.html" \
  "$core_versioned/user-guide/index.html"    "user-guide/index.html" \
  "$core_versioned/release-notes/index.html" "release-notes/index.html"

# Section: core latest alias
if [[ "$check_latest" -eq 1 ]]; then
  core_latest="$pages_abs/latest/core"
  run_section "Core latest alias (latest/core/)" \
    "$core_latest" \
    "$core_latest/index.html"               "index.html" \
    "$core_latest/user-guide/index.html"    "user-guide/index.html" \
    "$core_latest/release-notes/index.html" "release-notes/index.html"
else
  printf '\nCore latest alias (latest/core/)\n'
  skip "not checked (pass --check-latest to include)"
fi

# Section: demo versioned slides
if [[ -n "$demo_tag" ]]; then
  demo_versioned="$pages_abs/versions/$demo_tag/demo/slides"
  printf '\nDemo versioned slides (versions/%s/demo/slides/)\n' "$demo_tag"
  if [[ ! -d "$demo_versioned" ]]; then
    fail "directory does not exist: versions/$demo_tag/demo/slides"
    printf '  -> %smissing%s\n' "$C_FAIL" "$C_RESET"
    missing_count=$((missing_count + 1))
  else
    # Count slide decks; require at least one nonzero .html file.
    shopt -s nullglob
    slide_files=("$demo_versioned"/*.html)
    shopt -u nullglob
    nonzero=0
    empty=0
    for f in "${slide_files[@]}"; do
      if [[ -s "$f" ]]; then nonzero=$((nonzero + 1)); else empty=$((empty + 1)); fi
    done
    if [[ "$nonzero" -gt 0 && "$empty" -eq 0 ]]; then
      pass "$nonzero slide deck(s) present"
      printf '  -> %splausible%s\n' "$C_PASS" "$C_RESET"
      plausible_count=$((plausible_count + 1))
    elif [[ "$nonzero" -gt 0 ]]; then
      pass "$nonzero slide deck(s) present"
      fail "$empty slide deck(s) empty"
      printf '  -> %spartial%s\n' "$C_WARN" "$C_RESET"
      partial_count=$((partial_count + 1))
    else
      fail "no slide deck(s) present"
      printf '  -> %spartial%s (directory present but empty)\n' "$C_WARN" "$C_RESET"
      partial_count=$((partial_count + 1))
    fi
  fi
fi

# Section: demo latest alias
if [[ -n "$demo_tag" && "$check_latest" -eq 1 ]]; then
  demo_latest="$pages_abs/latest/demo/slides"
  printf '\nDemo latest alias (latest/demo/slides/)\n'
  if [[ ! -d "$demo_latest" ]]; then
    fail "directory does not exist: latest/demo/slides"
    printf '  -> %smissing%s\n' "$C_FAIL" "$C_RESET"
    missing_count=$((missing_count + 1))
  else
    shopt -s nullglob
    slide_files=("$demo_latest"/*.html)
    shopt -u nullglob
    nonzero=0
    empty=0
    for f in "${slide_files[@]}"; do
      if [[ -s "$f" ]]; then nonzero=$((nonzero + 1)); else empty=$((empty + 1)); fi
    done
    if [[ "$nonzero" -gt 0 && "$empty" -eq 0 ]]; then
      pass "$nonzero slide deck(s) present"
      printf '  -> %splausible%s\n' "$C_PASS" "$C_RESET"
      plausible_count=$((plausible_count + 1))
    elif [[ "$nonzero" -gt 0 ]]; then
      pass "$nonzero slide deck(s) present"
      fail "$empty slide deck(s) empty"
      printf '  -> %spartial%s\n' "$C_WARN" "$C_RESET"
      partial_count=$((partial_count + 1))
    else
      fail "no slide deck(s) present"
      printf '  -> %spartial%s\n' "$C_WARN" "$C_RESET"
      partial_count=$((partial_count + 1))
    fi
  fi
fi

# ------------------------------------------------------------
# Summary + exit
# ------------------------------------------------------------
printf '\nSummary: %d plausible, %d partial, %d missing.\n' \
  "$plausible_count" "$partial_count" "$missing_count"

if [[ "$missing_count" -gt 0 ]]; then
  printf '%sAt least one expected section is missing entirely.%s ' "$C_FAIL" "$C_RESET"
  printf 'Likely cause: publish job did not run, or pages checkout is not pulled.\n'
  exit 2
elif [[ "$partial_count" -gt 0 ]]; then
  printf '%sAt least one section is partial%s; review the failures above.\n' "$C_WARN" "$C_RESET"
  exit 1
else
  printf '%sStructurally plausible publish.%s ' "$C_PASS" "$C_RESET"
  printf 'This does not validate page content or external accessibility.\n'
  exit 0
fi
