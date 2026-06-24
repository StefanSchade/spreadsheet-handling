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
  scripts/reformation_slice.sh driver NAME [--source PATH]... [--test-hint PATH]...

NAME must use lowercase letters, numbers, and hyphens, for example:
  fk-helper-unresolved-values

The driver command prints a reusable agent prompt. It does not create files,
make semantic decisions, or update project memory.
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

append_driver_arg() {
  local flag="$1"
  local value="${2:-}"
  if [[ -z "$value" ]]; then
    printf 'reformation_slice: %s requires a value\n' "$flag" >&2
    exit 2
  fi
  printf '%s' "$value"
}

print_bullets_or_placeholder() {
  local placeholder="$1"
  shift
  if [[ "$#" -eq 0 ]]; then
    printf '* %s\n' "$placeholder"
    return
  fi

  local item
  for item in "$@"; do
    printf '* `%s`\n' "$item"
  done
}

print_driver_prompt() {
  local name="$1"
  shift
  local sources=()
  local test_hints=()
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --source)
        shift
        sources+=("$(append_driver_arg "--source" "${1:-}")")
        shift
        ;;
      --test-hint)
        shift
        test_hints+=("$(append_driver_arg "--test-hint" "${1:-}")")
        shift
        ;;
      *)
        printf 'reformation_slice: unexpected driver argument: %s\n' "$1" >&2
        usage >&2
        exit 2
        ;;
    esac
  done

  local slice_file="docs/warm_storage/domain_reformation/slices/$name/slice.adoc"

  cat <<EOF
Start reformation slice \`$name\` using the domain/meta reformation driver.

Operating rules:

* Treat Functional Model intent as the primary source. Use current
  implementation only after extracting functional requirements and decision
  points.
* Do not make semantic decisions silently.
* Do not add a conceptual model, Project Memory layer, backlog/ADR material, or
  semantic vocabulary unless a human explicitly approves it inside this slice.
* Do not delete old implementation paths without contract-test coverage and
  explicit human approval.
* Keep the slice narrow; optimize for contract-first progress, not more prose.

Read first:

* \`docs/warm_storage/domain_reformation/slice_automation_protocol.adoc\`
* \`docs/warm_storage/domain_reformation/slice_tooling_howto.adoc\`
* \`docs/ai_info/_ai_info.adoc\`
* \`docs/ai_info/agent_rules.adoc\`
* \`docs/ai_info/conventions.adoc\`
* \`docs/ai_info/interfaces_and_gates.adoc\`
* \`docs/ai_info/git_and_workflow.adoc\`
* \`$slice_file\` if it already exists; otherwise scaffold it with
  \`make reformation-slice NAME=$name\` before drafting slice content.

Functional Model / inquiry source hints:
EOF
  print_bullets_or_placeholder \
    "(none provided; discover candidate Functional Model or inquiry sources, then stop if the functional intent is ambiguous)" \
    "${sources[@]}"
  cat <<'EOF'

Test-location hints:
EOF
  print_bullets_or_placeholder \
    "(none provided; inspect nearby unit, integration, roundtrip, and architecture tests after the contract direction is clear)" \
    "${test_hints[@]}"
  cat <<EOF

Workflow:

1. Fresh-read the required guidance and the Functional Model / inquiry sources.
2. Extract the user-facing intent in plain language. Keep implementation
   sediment separate from functional intent.
3. List decision points before proposing a contract. Include uncertainty and
   any missing human input.
4. Human gate: stop for approval before accepting the bridge contract,
   lifecycle semantics, public-surface changes, semantic vocabulary, Project
   Memory/backlog/ADR changes, or old-path deletion.
5. Plan contract tests that express the Functional Model requirement. Name exact
   test files or nodes and the targeted verification command before
   implementation.
6. Implement only the smallest vNext path needed to satisfy the approved
   contract tests. Existing old paths may delegate narrowly; unrelated paths
   remain untouched.
7. Run the targeted tests, then the relevant structural checks:
   \`make reformation-check SLICE=$name\` and any test command named in the
   slice.
8. Self-review the slice: compare implementation and tests against the approved
   contract, note deviations, and fix narrow review findings.
9. Close with a concise report containing:
   * Functional intent used
   * Approved contract decision
   * Human gates reached and outcomes
   * Tests added or changed
   * Implementation files changed
   * Validation commands and results
   * Old-path handling
   * Memory/backlog/ADR impact, defaulting to "none" unless explicitly approved

Do not proceed past a human gate by inference. If the slice lacks enough
Functional Model material to define the contract, report that and stop before
implementation.
EOF
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
    driver)
      local name
      name="$(require_name "${1:-}")"
      shift || true
      print_driver_prompt "$name" "$@"
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      printf 'reformation_slice: expected command create, check, or driver\n' >&2
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
