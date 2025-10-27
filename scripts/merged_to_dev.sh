#! /bin/bash
# Usage:
#   scripts/merged_into.sh [base_branch]
# Examples:
#   scripts/merged_into.sh          # defaults to dev
#   scripts/merged_into.sh main

set -euo pipefail
BASE="${1:-dev}"

echo "Fetching origin..."
git fetch --all --prune --tags >/dev/null

git for-each-ref --format='%(refname:short)' refs/remotes/origin \
| grep -v -E '^origin/HEAD' \
| grep -E '^(origin/(feature|refactor|modularization)/)' \
| grep -v -E '^(origin/feature/xlsx-backend-refactor)$' \
| while read -r RB; do
  if git merge-base --is-ancestor "$RB" "origin/$BASE"; then
    printf "MERGED → %s (into %s)\n" "$RB" "$BASE"
  fi
done
