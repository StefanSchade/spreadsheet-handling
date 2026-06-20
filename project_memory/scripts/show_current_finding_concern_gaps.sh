#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DERIVED="$REPO_ROOT/project_memory/derived/finding_concern_mapping_gaps.json"

if [[ ! -f "$DERIVED" ]]; then
  echo "finding_concern_mapping_gaps.json not found. Run make memory-query first." >&2
  exit 1
fi

jq -r '
  map(select(.current_relevance == "current" or .current_relevance == "partial")) |
  sort_by(-((.normalized_value | tonumber?) // -1))[] |
  [.finding_id, .severity, .current_relevance, .normalized_value, .gap_reason, .topic] |
  @tsv
' "$DERIVED" \
| column -t -s $'\t' \
| less -S
