#!/usr/bin/env bash
# release_status.sh -- One-shot cross-repo release state summary (read-only).
#
# Inspects local checkouts of `spreadsheet-handling` (core),
# `spreadsheet-handling-demo` (demo), and `spreadsheet-handling-pages`
# (pages) and prints a single-screen factual summary plus a likely
# next-action hint based on internal consistency:
#
#   * per-repo: branch, working-tree state, HEAD short SHA, latest `v*`
#     tag, ahead/behind vs origin;
#   * demo: pinned core version extracted from `pyproject.toml`;
#   * pages: which versioned `core/` and `demo/` subtrees exist;
#   * cross-correlation: does the demo pin match the core latest tag?
#     does pages have a versioned snapshot for that tag pair?
#
# This is an orchestration aid for the multi-repo release flow
# documented in
# `docs/developer_guide/ch09_release_management/02_release_runbook.adoc`.
# It complements two existing read-only helpers:
#
#   * `release_check.sh`        - pre-tag branch/topology check
#   * `pages_publish_check.sh`  - post-deploy Pages structural check
#
# Where those answer "is this specific step ready/done?", this one
# answers "where am I across all three repos right now, and what is the
# next likely action?".
#
# Usage:
#   release_status.sh                                  # auto-detect siblings
#   release_status.sh --core ../core --demo ../demo --pages ../pages
#
# Env (alternative to flags):
#   CORE_DIR    path to core checkout
#               (default: try $PWD and ../core / ../spreadsheet-handling)
#   DEMO_DIR    path to demo checkout
#               (default: try ../demo / ../spreadsheet-handling-demo)
#   PAGES_DIR   path to pages checkout
#               (default: try ../pages / ../spreadsheet-handling-pages)
#
# Read-only contract:
#   No git operations that write. No fetch. No working-tree modification.
#   No network calls. No invocation of `gh`, `curl`, PyPI, or anything
#   beyond local file reads and read-only git plumbing.
#
# Exit codes:
#   0   summary rendered successfully (regardless of internal consistency)
#   3   setup error (a required sibling checkout could not be located)

set -euo pipefail

# ------------------------------------------------------------
# Argument parsing
# ------------------------------------------------------------
core_dir="${CORE_DIR:-}"
demo_dir="${DEMO_DIR:-}"
pages_dir="${PAGES_DIR:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --core)  core_dir="${2:?--core requires a path}";  shift 2 ;;
    --demo)  demo_dir="${2:?--demo requires a path}";  shift 2 ;;
    --pages) pages_dir="${2:?--pages requires a path}"; shift 2 ;;
    -h|--help)
      sed -n '2,46p' "$0"
      exit 0
      ;;
    *)
      printf 'release_status: unknown argument: %s\n' "$1" >&2
      exit 3
      ;;
  esac
done

# ------------------------------------------------------------
# Color helpers (terminal only)
# ------------------------------------------------------------
if [[ -t 1 ]]; then
  C_BOLD="$(printf '\033[1m')"
  C_DIM="$(printf '\033[2m')"
  C_OK="$(printf '\033[32m')"
  C_WARN="$(printf '\033[33m')"
  C_RESET="$(printf '\033[0m')"
else
  C_BOLD=""; C_DIM=""; C_OK=""; C_WARN=""; C_RESET=""
fi

# ------------------------------------------------------------
# Sibling auto-detection
# ------------------------------------------------------------
# A directory is treated as a checkout of a known repo if it contains a
# .git directory (or file, for worktrees) AND one of the marker files
# specific to that repo. Markers stay loose on purpose: the helper is
# operator-facing, not a strict validator.
is_core()  { [[ -e "$1/.git" && -f "$1/pyproject.toml" && -d "$1/src/spreadsheet_handling" ]]; }
is_demo()  { [[ -e "$1/.git" && -f "$1/pyproject.toml" && -d "$1/pipelines" ]]; }
is_pages() { [[ -e "$1/.git" && -f "$1/.nojekyll" ]]; }

auto_locate() {
  local kind="$1"; shift
  local check_fn="is_$kind"
  for candidate in "$@"; do
    if "$check_fn" "$candidate"; then
      ( cd "$candidate" && pwd )
      return 0
    fi
  done
  return 1
}

validate_checkout() {
  local kind="$1" dir="$2"
  local check_fn="is_$kind"
  if ! "$check_fn" "$dir"; then
    printf 'release_status: %s checkout is not valid: %s\n' "$kind" "$dir" >&2
    printf '  Pass --%s PATH or set %s_DIR to a matching local checkout.\n' \
      "$kind" "${kind^^}" >&2
    exit 3
  fi
}

normalize_dir() {
  ( cd "$1" && pwd )
}

git_read() {
  GIT_OPTIONAL_LOCKS=0 git "$@"
}

if [[ -z "$core_dir" ]]; then
  core_dir="$(auto_locate core "$PWD" "../core" "../spreadsheet-handling" 2>/dev/null || true)"
fi
if [[ -z "$demo_dir" ]]; then
  demo_dir="$(auto_locate demo "../demo" "../spreadsheet-handling-demo" 2>/dev/null || true)"
fi
if [[ -z "$pages_dir" ]]; then
  pages_dir="$(auto_locate pages "../pages" "../spreadsheet-handling-pages" 2>/dev/null || true)"
fi

if [[ -z "$core_dir" ]]; then
  printf 'release_status: could not locate core checkout.\n' >&2
  printf '  Pass --core PATH or set CORE_DIR; or run from a workspace where\n' >&2
  printf '  $PWD, ../core, or ../spreadsheet-handling is the core repo.\n' >&2
  exit 3
fi

validate_checkout core "$core_dir"
core_dir="$(normalize_dir "$core_dir")"

# Demo and pages are optional. If absent, the helper still reports core
# state and notes the missing sibling.
if [[ -n "$demo_dir" ]]; then
  validate_checkout demo "$demo_dir"
  demo_dir="$(normalize_dir "$demo_dir")"
fi
if [[ -n "$pages_dir" ]]; then
  validate_checkout pages "$pages_dir"
  pages_dir="$(normalize_dir "$pages_dir")"
fi

# ------------------------------------------------------------
# Per-repo state extraction (read-only git plumbing)
# ------------------------------------------------------------

# git_field DIR FIELD -> prints field, or "?" if not resolvable.
git_field() {
  local dir="$1" field="$2"
  case "$field" in
    branch)
      git_read -C "$dir" symbolic-ref --quiet --short HEAD 2>/dev/null || echo "DETACHED"
      ;;
    head_short)
      git_read -C "$dir" rev-parse --short HEAD 2>/dev/null || echo "?"
      ;;
    clean)
      if [[ -z "$(git_read -C "$dir" status --porcelain 2>/dev/null)" ]]; then
        echo "clean"
      else
        echo "dirty"
      fi
      ;;
    latest_tag)
      # Newest annotated or lightweight tag matching v* by topology
      # (not lexical). Falls back silently if no tag exists.
      git_read -C "$dir" describe --tags --abbrev=0 --match 'v*' 2>/dev/null || echo "(none)"
      ;;
    ahead_behind)
      local branch
      branch="$(git_field "$dir" branch)"
      local remote_ref="refs/remotes/origin/$branch"
      if ! git_read -C "$dir" rev-parse --verify --quiet "$remote_ref" >/dev/null 2>&1; then
        echo "no-remote"
        return
      fi
      local ahead behind
      ahead="$(git_read -C "$dir" rev-list --count "origin/$branch..HEAD" 2>/dev/null || echo '?')"
      behind="$(git_read -C "$dir" rev-list --count "HEAD..origin/$branch" 2>/dev/null || echo '?')"
      printf '%s ahead, %s behind' "$ahead" "$behind"
      ;;
  esac
}

# tag_at_head DIR TAG -> "yes"/"no"
tag_at_head() {
  local dir="$1" tag="$2"
  [[ -z "$tag" || "$tag" == "(none)" ]] && { echo "n/a"; return; }
  local tag_sha head_sha
  tag_sha="$(git_read -C "$dir" rev-parse --verify --quiet "$tag^{commit}" 2>/dev/null || echo "")"
  head_sha="$(git_read -C "$dir" rev-parse HEAD 2>/dev/null || echo "")"
  [[ -n "$tag_sha" && "$tag_sha" == "$head_sha" ]] && echo "yes" || echo "no"
}

# demo_pinned_core_version DEMO_DIR -> e.g. "0.1.0b6"; "?" on failure.
demo_pinned_core_version() {
  local dir="$1"
  local py="$dir/pyproject.toml"
  [[ -f "$py" ]] || { echo "?"; return; }
  # Match: spreadsheet-handling==X.Y.Z (with optional pre-release suffix).
  # Avoid Python dependency by using grep/sed.
  local line
  line="$(grep -E '^\s*"spreadsheet-handling==' "$py" 2>/dev/null | head -1)"
  if [[ -z "$line" ]]; then
    echo "?"
    return
  fi
  printf '%s' "$line" | sed -E 's/.*spreadsheet-handling==([^"]*)".*/\1/'
}

# pages_versioned_core_tags PAGES_DIR -> newline-separated, sorted by name
pages_versioned_core_tags() {
  local dir="$1"
  [[ -d "$dir/versions" ]] || return 0
  find "$dir/versions" -maxdepth 2 -mindepth 2 -type d -name core 2>/dev/null \
    | while IFS= read -r path; do
        path="${path#"$dir/versions/"}"
        printf '%s\n' "${path%/core}"
      done \
    | sort -u
}

# pages_versioned_demo_tags PAGES_DIR -> newline-separated, sorted by name
pages_versioned_demo_tags() {
  local dir="$1"
  [[ -d "$dir/versions" ]] || return 0
  find "$dir/versions" -maxdepth 2 -mindepth 2 -type d -name demo 2>/dev/null \
    | while IFS= read -r path; do
        path="${path#"$dir/versions/"}"
        printf '%s\n' "${path%/demo}"
      done \
    | sort -u
}

# ------------------------------------------------------------
# Collect state
# ------------------------------------------------------------
core_branch="$(git_field "$core_dir" branch)"
core_clean="$(git_field "$core_dir" clean)"
core_head="$(git_field "$core_dir" head_short)"
core_ahead_behind="$(git_field "$core_dir" ahead_behind)"
core_latest_tag="$(git_field "$core_dir" latest_tag)"
core_tag_at_head="$(tag_at_head "$core_dir" "$core_latest_tag")"

if [[ -n "$demo_dir" ]]; then
  demo_branch="$(git_field "$demo_dir" branch)"
  demo_clean="$(git_field "$demo_dir" clean)"
  demo_head="$(git_field "$demo_dir" head_short)"
  demo_ahead_behind="$(git_field "$demo_dir" ahead_behind)"
  demo_latest_tag="$(git_field "$demo_dir" latest_tag)"
  demo_pinned_core="$(demo_pinned_core_version "$demo_dir")"
fi

if [[ -n "$pages_dir" ]]; then
  pages_core_tags="$(pages_versioned_core_tags "$pages_dir")"
  pages_demo_tags="$(pages_versioned_demo_tags "$pages_dir")"
fi

# ------------------------------------------------------------
# Render
# ------------------------------------------------------------
printf '%srelease_status%s\n' "$C_BOLD" "$C_RESET"

printf '\n%score%s   %s\n' "$C_BOLD" "$C_RESET" "$core_dir"
printf '  branch=%s (%s) HEAD=%s vs origin: %s\n' \
  "$core_branch" "$core_clean" "$core_head" "$core_ahead_behind"
printf '  latest v*-tag=%s (at HEAD: %s)\n' "$core_latest_tag" "$core_tag_at_head"

if [[ -n "$demo_dir" ]]; then
  printf '\n%sdemo%s   %s\n' "$C_BOLD" "$C_RESET" "$demo_dir"
  printf '  branch=%s (%s) HEAD=%s vs origin: %s\n' \
    "$demo_branch" "$demo_clean" "$demo_head" "$demo_ahead_behind"
  printf '  latest v*-tag=%s   pinned core=%s\n' \
    "$demo_latest_tag" "$demo_pinned_core"
else
  printf '\n%sdemo%s   %s(not located; pass --demo PATH or set DEMO_DIR)%s\n' \
    "$C_BOLD" "$C_RESET" "$C_DIM" "$C_RESET"
fi

if [[ -n "$pages_dir" ]]; then
  printf '\n%spages%s  %s\n' "$C_BOLD" "$C_RESET" "$pages_dir"
  if [[ -n "$pages_core_tags" ]]; then
    printf '  versioned core/ snapshots: %s\n' \
      "$(printf '%s' "$pages_core_tags" | tr '\n' ' ')"
  else
    printf '  versioned core/ snapshots: (none)\n'
  fi
  if [[ -n "$pages_demo_tags" ]]; then
    printf '  versioned demo/ snapshots: %s\n' \
      "$(printf '%s' "$pages_demo_tags" | tr '\n' ' ')"
  else
    printf '  versioned demo/ snapshots: (none)\n'
  fi
else
  printf '\n%spages%s  %s(not located; pass --pages PATH or set PAGES_DIR)%s\n' \
    "$C_BOLD" "$C_RESET" "$C_DIM" "$C_RESET"
fi

# ------------------------------------------------------------
# Cross-correlation + next-action hint
# ------------------------------------------------------------
printf '\n%scross-correlation%s\n' "$C_BOLD" "$C_RESET"

issues=0
visibility_gaps=0

# Strip leading 'v' from core_latest_tag (if any) for pyproject comparison.
core_latest_stripped=""
if [[ "$core_latest_tag" =~ ^v.+ ]]; then
  core_latest_stripped="${core_latest_tag#v}"
fi

if [[ -z "$demo_dir" ]]; then
  printf '  %s!%s demo checkout not located; demo pin/tag not checked\n' \
    "$C_WARN" "$C_RESET"
  visibility_gaps=$((visibility_gaps + 1))
elif [[ "$core_latest_tag" != "(none)" && -n "$core_latest_stripped" ]]; then
  if [[ "$demo_pinned_core" == "$core_latest_stripped" ]]; then
    printf '  %s=%s demo pyproject pin matches core latest tag (%s)\n' \
      "$C_OK" "$C_RESET" "$core_latest_tag"
  elif [[ "$demo_pinned_core" == "?" ]]; then
    printf '  %s!%s could not parse demo pyproject core pin\n' \
      "$C_WARN" "$C_RESET"
    issues=$((issues + 1))
  else
    printf '  %s!%s demo pin (%s) differs from core latest tag (%s)\n' \
      "$C_WARN" "$C_RESET" "$demo_pinned_core" "$core_latest_tag"
    issues=$((issues + 1))
  fi
fi

if [[ -z "$pages_dir" ]]; then
  printf '  %s!%s pages checkout not located; pages snapshots not checked\n' \
    "$C_WARN" "$C_RESET"
  visibility_gaps=$((visibility_gaps + 1))
elif [[ "$core_latest_tag" != "(none)" ]]; then
  if printf '%s' "$pages_core_tags" | grep -Fxq "$core_latest_tag"; then
    printf '  %s=%s pages has versions/%s/core/ snapshot\n' \
      "$C_OK" "$C_RESET" "$core_latest_tag"
  else
    printf '  %s!%s pages missing versions/%s/core/ snapshot\n' \
      "$C_WARN" "$C_RESET" "$core_latest_tag"
    issues=$((issues + 1))
  fi
fi

if [[ -n "$pages_dir" && -n "${demo_latest_tag:-}" && "$demo_latest_tag" != "(none)" ]]; then
  if printf '%s' "$pages_demo_tags" | grep -Fxq "$demo_latest_tag"; then
    printf '  %s=%s pages has versions/%s/demo/ snapshot\n' \
      "$C_OK" "$C_RESET" "$demo_latest_tag"
  else
    printf '  %s!%s pages missing versions/%s/demo/ snapshot\n' \
      "$C_WARN" "$C_RESET" "$demo_latest_tag"
    issues=$((issues + 1))
  fi
fi

# ------------------------------------------------------------
# Next-action hint
# ------------------------------------------------------------
printf '\n%snext likely action%s\n' "$C_BOLD" "$C_RESET"
if [[ "$core_latest_tag" == "(none)" ]]; then
  printf '  no core release tags yet -- ship the first tag from core main\n'
  printf '  per runbook §"Core Release Checklist".\n'
elif [[ "$visibility_gaps" -gt 0 ]]; then
  printf '  local view is incomplete (%d sibling checkout(s) not located).\n' \
    "$visibility_gaps"
  if [[ "$issues" -gt 0 ]]; then
    printf '  available state also has %d cross-correlation issue(s); resolve\n' \
      "$issues"
    printf '  those after locating the missing sibling checkout(s).\n'
  else
    printf '  locate the missing sibling checkout(s) before deciding the next\n'
    printf '  release action.\n'
  fi
elif [[ "$issues" -eq 0 ]]; then
  printf '  cross-repo state appears coherent for %s.\n' "$core_latest_tag"
  printf '  next release: cut a new core tag from main per runbook §"Core Release Checklist".\n'
else
  printf '  state is mid-flight or inconsistent (%d cross-correlation issue(s)).\n' "$issues"
  if [[ -n "${demo_pinned_core:-}" \
        && -n "$core_latest_stripped" \
        && "$demo_pinned_core" != "$core_latest_stripped" \
        && "$demo_pinned_core" != "?" ]]; then
    printf '    -> demo alignment likely owed: update demo pyproject pin to %s,\n' \
      "$core_latest_stripped"
    printf '       run demo test suite, commit, tag %s-demo, push.\n' \
      "$core_latest_tag"
  fi
  if [[ -n "$pages_dir" ]] \
     && [[ "$core_latest_tag" != "(none)" ]] \
     && ! printf '%s' "$pages_core_tags" | grep -Fxq "$core_latest_tag"; then
    printf '    -> pages missing core snapshot for %s: check publish-docs job;\n' \
      "$core_latest_tag"
    printf '       see runbook §"Post-Deploy Pages Validation" (make pages-check).\n'
  fi
  printf '  cross-reference: runbook §"Cross-Repo Recovery Scenarios" for the\n'
  printf '  full recovery catalog.\n'
fi

printf '\n%sread-only check%s: no git writes, no network calls, no publishing.\n' \
  "$C_DIM" "$C_RESET"
