# CLAUDE.md — Project Context for AI Agents

## Project Identity

**spreadsheet-handling** — A Python toolkit for converting tabular data between formats
(JSON, CSV, XLSX, ODS, YAML) with relational structure preservation (foreign keys,
indexes, hierarchies). Enables round-tripping of complex spreadsheet models.

- **Version**: 0.1.0-beta (PyPI: `spreadsheet-handling`)
- **Python**: ≥ 3.10
- **License**: MIT
- **Status**: Pre-release; interfaces may change without deprecation

## Related Repository

`spreadsheet-handling-demo` — Tutorial/demo repo that consumes this package.
Both repos live side-by-side in the workspace for shared context.

## Architecture

Hexagonal architecture (ADR-001), pragmatic Python variant:

```
CLI Layer (sheets-run, sheets-pack, sheets-unpack)
    ↓
Orchestrator (orchestrate())
    ↓
Pipeline Engine (Step = Frames → Frames)
    ↓
Domain Logic (validations, transformations, extractions)
    ↓
I/O Backends (json_dir, yaml_dir, xlsx, csv_dir, ods)
    ↓
Rendering IR (for spreadsheet backends: XLSX, ODS)
```

**Key abstractions**:
- `Frames = Dict[str, pd.DataFrame]` — central data type
- `Step` — pure function `Frames → Frames`
- `Meta` — structured dict for column roles, validation, styling
- `RenderPlan` / IR — backend-agnostic spreadsheet layout model
- Pandas DataFrames are intentionally part of the domain (ADR-002)

## Module Map

| Package | Purpose |
|---------|---------|
| `cli/` | Entry points: `sheets-run`, `sheets-pack`, `sheets-unpack` |
| `core/` | DataFrame building, FK detection, flatten/unflatten, indexing |
| `domain/validations/` | Column constraints, uniqueness, in-list checks |
| `domain/transformations/` | Helper columns, header flattening, FK reordering |
| `domain/extractions/` | Extraction step framework |
| `engine/` | EngineConfig, validation orchestration, FK helper application |
| `io_backends/` | Router + format-specific loaders/savers |
| `pipeline/` | Pipeline runner, step factories, AppConfig |
| `rendering/` | IR model, composer, passes (Style, Validation, Meta) |
| `orchestrator.py` | Unified `orchestrate()` entry point (WIP on feature branch) |

## Branching & Git

- **Strategy**: `main` → `dev` → `feature/*` (cascade)
- **Current branch**: `feature/one-orchestrator` (1 commit ahead of dev)
- **Merge policy**: rebase-merge (linear history)
- **Commits**: Conventional Commits with FTR-ID in scope
  ```
  feat(FTR-ONE-ORCHESTRATOR): add orchestrate() scaffold + smoke test
  ```

## Development Environment (Linux / WSL)

```bash
make venv           # create virtualenv
make deps           # install runtime dependencies (non-editable)
make dev            # install dev extras (editable)
make test           # run tests (excludes legacy)
make test-unit      # unit tests only
make test-integ     # integration tests
make test-ir        # IR backend tests (SH_XLSX_BACKEND=ir)
make test-legacy    # pre-hexagonal legacy tests
make test-all       # everything
make lint           # ruff + black check
make test-one TESTPATTERN="expr"  # filtered test run
```

Note: Makefile uses `/usr/bin/env bash` with `set -euo pipefail`. Run under WSL or Linux.

## Testing Conventions

- **Framework**: pytest with markers (`integ`, `legacy`, `slow`, `xlsx_ir`, `xlsx_legacy`)
- **Default**: `make test` excludes legacy
- **Style**: small in-memory DataFrames; assert schema, row count, keys
- **Hermetic**: no network dependencies; filesystem only for I/O tests

## Code Style

- **Formatter**: black (line-length 100)
- **Linter**: ruff (PEP 8 focus)
- **Type hints**: Required on all public functions (`from __future__ import annotations`)
- **Naming**: `snake_case` functions, `PascalCase` classes, `UPPERCASE` constants
- **Prefer**: Dataclasses, composition over inheritance, immutability

## Current Work State (feature/one-orchestrator)

**FTR-ONE-ORCHESTRATOR** — Single `orchestrate(pipeline, profile, io_overrides, ...)` function.

**Done**:
- `orchestrator.py` module with `orchestrate()` scaffold
- Smoke test (`tests/unit/test_orchestrator_smoke.py`)
- Makefile cleanup

**Remaining (this feature)**:
- Wire CLIs (`sheets-run`, `sheets-pack`, `sheets-unpack`) to call `orchestrate()`
- Add delegation/integration tests
- XLSX backend integration in orchestrator

## Backlog Overview (Phases)

| Phase | Focus | Status |
|-------|-------|--------|
| 1 | Stabilize & Modularize XLSX Backend | ✅ Complete |
| 2 | Domain Consistency & Meta Integration | 🔄 In Progress |
| 3 | IR Parity & Features (P1–P4 slices) | 🔄 Active |
| 4 | Feature Expansion & Domain Transforms | 📋 Planned |
| 5 | Integration & Demo Repository | 📋 Planned |
| 6 | Consolidate Domain & Cleanup | 📋 Planned |
| 7 | Final Polish for 1.0 | 📋 Planned |

**Key open features (Phase 2–3)**:
- `FTR-ONE-ORCHESTRATOR` — unified orchestrate() (current feature branch)
- `FTR-STYLE-THEMES` — centralized styling via IR StylePass
- `FTR-META-BOOTSTRAP` — fault-tolerant meta merging
- `FTR-MULTIHEADER-P2` — multi-row/column headers with merges
- `FTR-ROUNDTRIP-SAFE-P1` — controlled read path, safe edit rules
- `FTR-PARITY-IR-P3` — IR vs. legacy parity verification

Full backlog: `docs/internal_guide/backlog/`

## Architecture Decision Records

| ADR | Decision |
|-----|----------|
| ADR-001 | Hexagonal Architecture (pragmatic) |
| ADR-002 | Pandas as core data representation |
| ADR-003 | IR layer for spreadsheet rendering |
| ADR-004 | Meta as persistent/mergeable config |
| ADR-005 | Dual test harness (legacy vs. IR) |
| ADR-RENDER-FLOW | "Pipeline" = domain, "Render-Flow" = IR layer |

Full ADRs: `docs/internal_guide/architecture_decision_records/`

## Documentation Structure

- `docs/internal_guide/` — Architecture, backlog, ADRs, AI policy, dev manual, concepts
- `docs/user_guide/` — End-user documentation (AsciiDoc)
- Format: AsciiDoc with `include::[]` composition
- `'''` for horizontal separators (not `---`)

## AI Policy Summary

- AI tools used at all levels; all artifacts reviewed, tested, version-controlled
- Repo is deliberately AI-friendly: holds context for fresh-context continuation
- Primer and persona docs: `docs/internal_guide/ai_policy/`
- Language: English in repo; chat in English or German
- When unclear: ask at most one clarifying question, then proceed with safest assumption

## Sandboxing Rules

### Allowed
- Read/write files within the two workspace repos (`spreadsheet-handling`, `spreadsheet-handling-demo`)
- Git operations: commit, branch, checkout, pull, push, rebase (non-destructive)
- Run tests, linters, build commands via Makefile / pytest
- Create/delete branches for feature work

### Forbidden
- **No destructive git**: `git push --force`, `git reset --hard`, `git rebase` on shared branches, history rewriting
- **No publishing**: Do not publish releases to PyPI, create GitHub releases, or push tags without explicit user approval
- **No large binaries**: Do not generate or commit large binary files
- **No destructive actions outside repos**: Do not modify, delete, or create files outside the two workspace repos
- **No credential exposure**: Do not print, log, or transmit SSH keys, tokens, or secrets
- **No network services**: Do not start servers, open ports, or make outbound API calls beyond what tools provide
- **No bypassing safety checks**: Do not use `--no-verify`, skip linters, or disable test guards

### Ask First
- Merging feature branches into `dev` or `main`
- Creating or pushing git tags
- Modifying CI/CD configuration
- Deleting files that look like in-progress work
- Any action affecting shared infrastructure or public-facing artifacts

## Key Files for Quick Orientation

| File | Purpose |
|------|---------|
| `input.json` | Temporal working notes for current feature (not committed) |
| `pyproject.toml` | Single source of truth for deps, entry points, config |
| `Makefile` | Build/test/lint workflow (WSL/Linux) |
| `sheets.yaml` | Example profile-based config |
| `pipeline.yml` | Example pipeline definition |
| `docs/internal_guide/backlog/` | Complete phased backlog |
