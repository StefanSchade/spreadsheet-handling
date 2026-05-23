#!/usr/bin/env bash
# release_check.sh -- Pre-tag branch and topology sanity check (read-only).
#
# Usage:
#   release_check.sh                  # check current HEAD against the release branch
#   release_check.sh v0.1.0b7         # additionally validate the named tag
#
# Env:
#   RELEASE_BRANCH    canonical release branch (default: main)
#   REMOTE            git remote to compare against (default: origin)
#
# Read-only contract:
#   This script performs no git operations that write. It does not fetch
#   from the remote, does not update local refs, and does not modify the
#   working tree or the index. Run `git fetch <remote>` yourself before
#   invoking the check if you want to validate against the latest remote
#   state; if the remote-tracking branch is missing locally, the check
#   fails with a hint to fetch first.
#
# Exit codes:
#   0   all blocking checks passed; safe to tag
#   1   one or more blocking checks failed; do not tag without explicit resolution
#   2   usage error (not inside a git repository)

set -euo pipefail

RELEASE_BRANCH="${RELEASE_BRANCH:-main}"
REMOTE="${REMOTE:-origin}"
TAG="${1:-}"

# Color output only when stdout is a terminal.
if [[ -t 1 ]]; then
  C_PASS="$(printf '\033[32m')"
  C_WARN="$(printf '\033[33m')"
  C_FAIL="$(printf '\033[31m')"
  C_RESET="$(printf '\033[0m')"
else
  C_PASS=""; C_WARN=""; C_FAIL=""; C_RESET=""
fi

fail_count=0
warn_count=0

pass() { printf '  %sPASS%s  %s\n' "$C_PASS" "$C_RESET" "$1"; }
warn() { printf '  %sWARN%s  %s\n' "$C_WARN" "$C_RESET" "$1"; warn_count=$((warn_count + 1)); }
fail() { printf '  %sFAIL%s  %s\n' "$C_FAIL" "$C_RESET" "$1"; fail_count=$((fail_count + 1)); }

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  printf 'release_check: not inside a git repository\n' >&2
  exit 2
fi

current_branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || echo "DETACHED")"
head_sha="$(git rev-parse HEAD)"

printf 'release_check: HEAD=%s on %s, compare against %s/%s\n' \
  "$(git rev-parse --short HEAD)" "$current_branch" "$REMOTE" "$RELEASE_BRANCH"
[[ -n "$TAG" ]] && printf '              tag argument: %s\n' "$TAG"
printf 'Note: this check does not fetch; run `git fetch %s` first for fresh remote state.\n\n' "$REMOTE"

# ------------------------------------------------------------
# Check 1: current branch
# ------------------------------------------------------------
printf 'Branch state\n'
if [[ "$current_branch" == "$RELEASE_BRANCH" ]]; then
  pass "on the release branch ($RELEASE_BRANCH)"
elif [[ "$current_branch" == "DETACHED" ]]; then
  fail "HEAD is detached; release tags must come from $RELEASE_BRANCH"
else
  fail "on $current_branch, not $RELEASE_BRANCH; release tags must come from $RELEASE_BRANCH"
fi

# ------------------------------------------------------------
# Check 2: working tree clean
# ------------------------------------------------------------
if [[ -z "$(git status --porcelain)" ]]; then
  pass "working tree is clean"
else
  fail "working tree has uncommitted changes; commit or stash before tagging"
fi

# ------------------------------------------------------------
# Check 3: remote branch known locally
# ------------------------------------------------------------
printf '\nTopology vs %s/%s\n' "$REMOTE" "$RELEASE_BRANCH"
remote_branch_ref="refs/remotes/$REMOTE/$RELEASE_BRANCH"
remote_branch_sha=""
if git rev-parse --verify --quiet "$remote_branch_ref" >/dev/null; then
  remote_branch_sha="$(git rev-parse "$remote_branch_ref")"
  pass "$REMOTE/$RELEASE_BRANCH is known locally"
else
  fail "$REMOTE/$RELEASE_BRANCH not known locally; run \`git fetch $REMOTE\` first, then re-run"
fi

# ------------------------------------------------------------
# Check 4: local RELEASE_BRANCH vs remote RELEASE_BRANCH
# ------------------------------------------------------------
if [[ -n "$remote_branch_sha" ]] && git rev-parse --verify --quiet "refs/heads/$RELEASE_BRANCH" >/dev/null; then
  local_branch_sha="$(git rev-parse "refs/heads/$RELEASE_BRANCH")"
  if [[ "$local_branch_sha" == "$remote_branch_sha" ]]; then
    pass "local $RELEASE_BRANCH is in sync with $REMOTE/$RELEASE_BRANCH"
  else
    ahead="$(git rev-list --count "$remote_branch_sha..$local_branch_sha" 2>/dev/null || echo 0)"
    behind="$(git rev-list --count "$local_branch_sha..$remote_branch_sha" 2>/dev/null || echo 0)"
    if [[ "$ahead" != "0" && "$behind" == "0" ]]; then
      fail "local $RELEASE_BRANCH is $ahead commit(s) ahead of $REMOTE/$RELEASE_BRANCH; push before tagging"
    elif [[ "$ahead" == "0" && "$behind" != "0" ]]; then
      fail "local $RELEASE_BRANCH is $behind commit(s) behind $REMOTE/$RELEASE_BRANCH; fast-forward before tagging"
    else
      fail "local $RELEASE_BRANCH has diverged from $REMOTE/$RELEASE_BRANCH ($ahead ahead, $behind behind); reconcile before tagging"
    fi
  fi
fi

# ------------------------------------------------------------
# Check 5: HEAD reachable from remote RELEASE_BRANCH
# ------------------------------------------------------------
if [[ -n "$remote_branch_sha" ]]; then
  if [[ "$head_sha" == "$remote_branch_sha" ]] \
     || git merge-base --is-ancestor "$head_sha" "$remote_branch_sha" 2>/dev/null; then
    pass "HEAD is reachable from $REMOTE/$RELEASE_BRANCH"
  else
    if git merge-base --is-ancestor "$remote_branch_sha" "$head_sha" 2>/dev/null; then
      ahead="$(git rev-list --count "$remote_branch_sha..$head_sha" 2>/dev/null || echo "?")"
      fail "HEAD is $ahead commit(s) ahead of $REMOTE/$RELEASE_BRANCH and not pushed; push $RELEASE_BRANCH before tagging"
    else
      fail "HEAD has diverged from $REMOTE/$RELEASE_BRANCH; the tag will not be reachable from $RELEASE_BRANCH"
    fi
  fi
fi

# ------------------------------------------------------------
# Check 6 (optional): named tag validation
# ------------------------------------------------------------
if [[ -n "$TAG" ]]; then
  printf '\nTag %s\n' "$TAG"
  if ! git rev-parse --verify --quiet "refs/tags/$TAG" >/dev/null; then
    fail "tag $TAG does not exist locally; create it from the intended commit on $RELEASE_BRANCH"
  else
    tag_sha="$(git rev-parse "$TAG^{commit}")"
    if [[ "$tag_sha" == "$head_sha" ]]; then
      pass "tag $TAG points at current HEAD"
    else
      warn "tag $TAG does not point at current HEAD (advisory; legitimate when tagging an earlier commit on $RELEASE_BRANCH)"
    fi
    if [[ -n "$remote_branch_sha" ]]; then
      if git merge-base --is-ancestor "$tag_sha" "$remote_branch_sha" 2>/dev/null; then
        pass "tag $TAG is reachable from $REMOTE/$RELEASE_BRANCH"
      else
        fail "tag $TAG is NOT reachable from $REMOTE/$RELEASE_BRANCH; the release would not sit on canonical history"
      fi
    fi
  fi
fi

# ------------------------------------------------------------
# Summary
# ------------------------------------------------------------
printf '\n'
if [[ "$fail_count" -eq 0 && "$warn_count" -eq 0 ]]; then
  printf '%sAll checks passed.%s Safe to tag.\n' "$C_PASS" "$C_RESET"
  exit 0
elif [[ "$fail_count" -eq 0 ]]; then
  printf '%s%d advisory warning(s).%s Review before tagging; warnings are non-blocking.\n' \
    "$C_WARN" "$warn_count" "$C_RESET"
  exit 0
else
  printf '%s%d failure(s)%s and %s%d advisory warning(s)%s. Do not tag until failures are resolved.\n' \
    "$C_FAIL" "$fail_count" "$C_RESET" "$C_WARN" "$warn_count" "$C_RESET"
  exit 1
fi
