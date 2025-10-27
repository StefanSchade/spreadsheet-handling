#! /bin/bash
# Usage:
#   scripts/print_delete_merged.sh [base_branch]
# Prints 'git push origin --delete ...' for branches merged into base.

set -euo pipefail
BASE="${1:-dev}"

git fetch --all --prune --tags >/dev/null

git for-each-ref --format='%(refname:short)' refs/remotes/origin \
| grep -v -E '^origin/HEAD' \
| grep -E '^(origin/(feature|refactor|modularization)/)' \
| grep -v -E '^(origin/feature/xlsx-backend-refactor)$' \
| while read -r RB; do
  if git merge-base --is-ancestor "$RB" "origin/$BASE"; then
    echo "git push origin --delete ${RB#origin/}"
  fi
done
