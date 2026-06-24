#!/usr/bin/env bash
# reformation_slice.sh -- scaffold and check domain reformation slice notes.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_DIR="$ROOT/docs/warm_storage/domain_reformation/slices"
INDEX="$BASE_DIR/_slices.adoc"

usage() {
  cat <<'EOF'
Usage:
  scripts/reformation_slice.sh create NAME
  scripts/reformation_slice.sh check NAME

NAME must use lowercase letters, numbers, and hyphens, for example:
  fk-helper-unresolved-values
EOF
}

require_name() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then
    printf 'reformation_slice: missing NAME\n' >&2
    usage >&2
    exit 2
  fi
  if [[ ! "$name" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
    printf 'reformation_slice: invalid NAME: %s\n' "$name" >&2
    usage >&2
    exit 2
  fi
  printf '%s' "$name"
}

title_from_name() {
  local name="$1"
  local words=()
  IFS='-' read -ra words <<< "$name"
  local out=()
  local word
  for word in "${words[@]}"; do
    out+=("${word^}")
  done
  printf '%s' "${out[*]}"
}

ensure_index() {
  mkdir -p "$BASE_DIR"
  if [[ ! -f "$INDEX" ]]; then
    cat > "$INDEX" <<'EOF'
== Reformation Slices

EOF
  fi
}

create_slice() {
  local name="$1"
  local dir="$BASE_DIR/$name"
  local file="$dir/slice.adoc"
  local title
  title="$(title_from_name "$name")"

  ensure_index
  mkdir -p "$dir"
  if [[ -e "$file" ]]; then
    printf 'reformation_slice: slice already exists: %s\n' "$file" >&2
    exit 1
  fi

  cat > "$file" <<EOF
= Reformation Slice: $title
:revdate: 2026-06
:slice-name: $name

== Status

Draft.

== Intent

TODO: State the user-facing requirement and why this slice exists.

== Functional Model Source

TODO: Link Functional Model chapters or inquiry documents used as primary
intent source.

== Bridge DSL Contract

TODO: State the minimal \`Frames + Meta\` information consumed and produced.

== Lifecycle Semantics

TODO: State which meta is durable, transient, consumed, deleted, or recreated.

== Contract Tests

TODO: Name the contract or integration tests that express the requirement.

== Implementation Shape

TODO: State the smallest vNext path that should satisfy the tests.

== Old-Path Handling

TODO: State whether old paths delegate, are deleted, or remain untouched with
rationale.

== Acceptance

TODO: State observable completion criteria.

== Memory / Backlog Impact

TODO: State whether Project Memory, ADRs, or backlog items are needed.

== Verification Command

[source,bash]
----
make reformation-check SLICE=$name
----
EOF

  local include_line="include::$name/slice.adoc[leveloffset=+1]"
  if ! grep -Fxq "$include_line" "$INDEX"; then
    {
      printf '%s\n' "$include_line"
      printf '\n'
    } >> "$INDEX"
  fi

  printf '%s\n' "$file"
}

check_slice() {
  local name="$1"
  local file="$BASE_DIR/$name/slice.adoc"
  local missing=0
  local headings=(
    "== Intent"
    "== Functional Model Source"
    "== Bridge DSL Contract"
    "== Lifecycle Semantics"
    "== Contract Tests"
    "== Implementation Shape"
    "== Old-Path Handling"
    "== Acceptance"
    "== Memory / Backlog Impact"
    "== Verification Command"
  )

  if [[ ! -f "$file" ]]; then
    printf 'FAIL missing slice document: %s\n' "$file" >&2
    exit 1
  fi

  local heading
  for heading in "${headings[@]}"; do
    if ! grep -Fxq "$heading" "$file"; then
      printf 'FAIL missing heading in %s: %s\n' "$file" "$heading" >&2
      missing=1
    fi
  done

  if ! command -v asciidoctor >/dev/null 2>&1; then
    printf 'WARN asciidoctor not found; skipped render check for %s\n' "$file"
  else
    asciidoctor --failure-level ERROR -o /tmp/reformation-slice-"$name".html "$file"
  fi

  if [[ "$missing" -ne 0 ]]; then
    exit 1
  fi

  printf 'PASS reformation slice structure: %s\n' "$file"
}

main() {
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    create)
      create_slice "$(require_name "${1:-}")"
      ;;
    check)
      check_slice "$(require_name "${1:-}")"
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      printf 'reformation_slice: expected command create or check\n' >&2
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
