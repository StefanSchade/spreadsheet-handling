#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DERIVED="$REPO_ROOT/project_memory/derived/concern_heatmap.json"

if [[ ! -f "$DERIVED" ]]; then
  echo "concern_heatmap.json not found. Run make memory-query first." >&2
  exit 1
fi

jq -r '
  .[] |
  [.concern_id, .concern_priority, .total_heat, .active_heat, .watch_heat, .finding_count, .top_finding_ids] |
  @tsv
' "$DERIVED" \
| column -t -s $'\t'
