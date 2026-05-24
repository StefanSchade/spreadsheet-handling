#!/usr/bin/env bash
# readme_links_check.sh -- README link-versioning check (read-only).
#
# The public README links to Pages documentation under two URL shapes:
#
#   https://stefanschade.github.io/spreadsheet-handling-pages/latest/...
#       living context -- moves with each release
#
#   https://stefanschade.github.io/spreadsheet-handling-pages/versions/<tag>/...
#       frozen context -- the snapshot for one specific release
#
# Per FTR-RELEASE-README-VERSION-BAKING-P5, any README that becomes a
# frozen public artifact -- a PyPI long description, a GitHub release
# page tied to a tag -- must carry `/versions/<tag>/...` links. A
# `/latest/...` link inside a frozen README silently sends an old PyPI
# release page's reader to documentation for a newer release that may
# describe a different product surface.
#
# This helper does the verification half of that policy. The
# substitution itself is a manual maintainer step on the release
# branch (see
# docs/developer_guide/ch09_release_management/02_release_runbook.adoc
# § "Release-bound README links"). The helper has two modes:
#
#   * Lint mode (default, no --release-tag): scan the README and list
#     every `…/spreadsheet-handling-pages/latest/...` URL it finds, one
#     per line, with the source line number. Always exits 0; this mode
#     is informational and is safe to run from `dev` without surprising
#     the maintainer.
#
#   * Release-tag mode (--release-tag <tag>): scan the README and fail
#     with a non-zero exit if any `…/spreadsheet-handling-pages/latest/`
#     URL remains. This is the mode wired into `make readme-check
#     TAG=vX.Y.Z` and into the release.yml CI guard, so a maintainer who
#     forgets to bake links on the release branch cannot silently ship
#     a PyPI release whose README points back at `/latest/...`.
#
# The helper deliberately does NOT modify the README. It does NOT call
# sed, write to the file system, or commit anything. The substitution
# stays a maintainer decision, and the helper only reports.
#
# Usage:
#   readme_links_check.sh                                      # lint ./README.md
#   readme_links_check.sh --file PATH                          # lint another file
#   readme_links_check.sh --release-tag v0.1.0b7               # enforce on ./README.md
#   readme_links_check.sh --release-tag v0.1.0b7 --file PATH   # enforce on PATH
#   readme_links_check.sh --help                               # print this header
#
# Substitution allowlist (per FTR §Implementation notes):
#   Only URLs that begin with the literal prefix
#   `https://stefanschade.github.io/spreadsheet-handling-pages/latest/`
#   are flagged. Other strings containing the word `latest` (prose,
#   shell snippets, asciidoctor output paths) are intentionally
#   ignored: the policy is about Pages URL shape, not about the word.
#
# Exit codes:
#   0   safe (lint mode always; release-tag mode when no /latest/
#       Pages URL remains in the scanned README)
#   1   release-tag mode found one or more /latest/ Pages URLs that
#       must be baked to /versions/<tag>/ before the tag is published
#   2   setup error (file missing, malformed --release-tag value,
#       conflicting arguments)

set -euo pipefail

PAGES_PREFIX="https://stefanschade.github.io/spreadsheet-handling-pages/"
LATEST_PREFIX="${PAGES_PREFIX}latest/"

RELEASE_TAG=""
README_FILE="./README.md"

print_help() {
  # Strip the leading `# ` from the header comment so the help text
  # matches what an operator sees in the file itself.
  sed -n '2,/^$/p' "$0" | sed -e 's/^# //' -e 's/^#//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release-tag)
      [[ -n "${2:-}" ]] || { printf 'readme_links_check: --release-tag requires an argument\n' >&2; exit 2; }
      RELEASE_TAG="$2"
      shift 2
      ;;
    --release-tag=*)
      RELEASE_TAG="${1#--release-tag=}"
      [[ -n "$RELEASE_TAG" ]] || { printf 'readme_links_check: --release-tag requires an argument\n' >&2; exit 2; }
      shift
      ;;
    --file)
      [[ -n "${2:-}" ]] || { printf 'readme_links_check: --file requires an argument\n' >&2; exit 2; }
      README_FILE="$2"
      shift 2
      ;;
    --file=*)
      README_FILE="${1#--file=}"
      shift
      ;;
    -h|--help)
      print_help
      exit 0
      ;;
    *)
      printf 'readme_links_check: unknown argument: %s\n' "$1" >&2
      printf 'Run with --help for usage.\n' >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$README_FILE" ]]; then
  printf 'readme_links_check: file does not exist: %s\n' "$README_FILE" >&2
  exit 2
fi

if [[ -n "$RELEASE_TAG" ]]; then
  # Format check: tag must start with `v` and not contain whitespace.
  # We deliberately do not enforce PEP 440 here -- the publisher
  # workflow already does that via packaging.version in the
  # latest_tag computation. A typo like `0.1.0b7` (missing v) is the
  # common failure mode and is worth catching early.
  if [[ ! "$RELEASE_TAG" =~ ^v[^[:space:]]+$ ]]; then
    printf 'readme_links_check: --release-tag must look like vX.Y.Z (got: %q)\n' \
      "$RELEASE_TAG" >&2
    exit 2
  fi
fi

# Color output only when stdout is a terminal.
if [[ -t 1 ]]; then
  C_PASS="$(printf '\033[32m')"
  C_FAIL="$(printf '\033[31m')"
  C_INFO="$(printf '\033[36m')"
  C_RESET="$(printf '\033[0m')"
else
  C_PASS=""; C_FAIL=""; C_INFO=""; C_RESET=""
fi

# Find every literal `…/latest/` URL in the file. grep -F keeps the
# match literal; -n includes the line number; -o would lose context,
# so we keep the full line. The substitution surface is fixed to one
# prefix string, so a single grep is sufficient and the allowlist is
# automatic.
mapfile -t LATEST_HITS < <(grep -nF "$LATEST_PREFIX" "$README_FILE" || true)

if [[ -n "$RELEASE_TAG" ]]; then
  printf 'readme_links_check: enforcing %sversions/%s/%s on %s\n' \
    "$C_INFO" "$RELEASE_TAG" "$C_RESET" "$README_FILE"

  if [[ ${#LATEST_HITS[@]} -eq 0 ]]; then
    printf '  %sPASS%s  no %s URLs remain; README links look frozen for %s\n' \
      "$C_PASS" "$C_RESET" "$LATEST_PREFIX" "$RELEASE_TAG"
    exit 0
  fi

  printf '  %sFAIL%s  %d %s URL(s) still present:\n' \
    "$C_FAIL" "$C_RESET" "${#LATEST_HITS[@]}" "$LATEST_PREFIX"
  for hit in "${LATEST_HITS[@]}"; do
    printf '    %s\n' "$hit"
  done
  printf '\nBake versioned links before tagging. See the release runbook\n'
  printf '§ "Release-bound README links" for the manual procedure. A common\n'
  printf 'one-liner:\n'
  printf '    sed -i "s#%s#%sversions/%s/#g" %s\n' \
    "$LATEST_PREFIX" "$PAGES_PREFIX" "$RELEASE_TAG" "$README_FILE"
  exit 1
fi

# Lint mode (no --release-tag).
printf 'readme_links_check: lint mode on %s\n' "$README_FILE"
if [[ ${#LATEST_HITS[@]} -eq 0 ]]; then
  printf '  %sclean%s  no %s URLs found.\n' "$C_INFO" "$C_RESET" "$LATEST_PREFIX"
  exit 0
fi

printf '  %sinfo%s  %d %s URL(s) (acceptable on the living `dev`/`main` README;\n' \
  "$C_INFO" "$C_RESET" "${#LATEST_HITS[@]}" "$LATEST_PREFIX"
printf '         must be baked to /versions/<tag>/ before a release tag):\n'
for hit in "${LATEST_HITS[@]}"; do
  printf '    %s\n' "$hit"
done
exit 0
