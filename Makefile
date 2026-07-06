# =========================
# Project variables
# =========================
SHELL        := /usr/bin/env bash
.SHELLFLAGS  := -eu -o pipefail -c

REPO := $(shell git rev-parse --show-toplevel 2>/dev/null | xargs basename)
VER  := $(shell git describe --tags --always --dirty 2>/dev/null || echo DEV-SNAPSHOT)
REV  := $(shell git rev-parse --short HEAD 2>/dev/null || echo local)
DATE := $(shell date -Iseconds)

ROOT          := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
BUILD_DIR     := $(ROOT)build
SNAPSHOT_MAX_FILES ?= 20
DOC_BUILD_DIR := $(BUILD_DIR)/doc
VENV          := $(ROOT).venv
COV_HTML_DIR  := $(BUILD_DIR)/htmlcov
COV_DATA      := $(BUILD_DIR)/.coverage

SYS_PY       ?= python3
SYS_PIP      ?= pip3

PYTHON       := $(VENV)/bin/python
PYTEST       := $(VENV)/bin/pytest
RUFF         := $(VENV)/bin/ruff
BLACK        := $(VENV)/bin/black
SHEETS_RUN   := $(VENV)/bin/sheets-run

MEMORY_DIR           := $(ROOT)project_memory
MEMORY_CANONICAL_DIR := $(MEMORY_DIR)/canonical
MEMORY_DERIVED_DIR   := $(MEMORY_DIR)/derived
MEMORY_STAGING_DIR   := $(MEMORY_DIR)/staging
MEMORY_PIPELINE_DIR  := $(MEMORY_DIR)/pipelines/memory

DOMAIN_CONTRACTS_DIR           := $(ROOT)registries/domain_contracts
DOMAIN_CONTRACTS_CANONICAL_DIR := $(DOMAIN_CONTRACTS_DIR)/canonical
DOMAIN_CONTRACTS_STAGING_DIR   := $(DOMAIN_CONTRACTS_DIR)/staging
DOMAIN_CONTRACTS_PIPELINE_DIR  := $(DOMAIN_CONTRACTS_DIR)/pipelines
DOMAIN_CONTRACTS_WORKBOOK      := $(DOMAIN_CONTRACTS_DIR)/domain_contracts.ods
DOMAIN_CONTRACTS_ODS_STAMP     := $(DOMAIN_CONTRACTS_DIR)/domain_contracts.ods.stamp.json
DOMAIN_CONTRACTS_STAGING_STAMP := $(DOMAIN_CONTRACTS_DIR)/staging/.export_stamp.json
DOMAIN_CONTRACTS_GENERATED_DIR := $(ROOT)docs_generated/domain_contracts
DOMAIN_CONTRACTS_BUILD_DIR     := $(BUILD_DIR)/domain_contracts

STAMP_DIR    := $(VENV)/.stamp
DEPS_STAMP   := $(STAMP_DIR)/deps
DEV_STAMP    := $(STAMP_DIR)/dev
PROJECT_MEMORY_STAMP := $(STAMP_DIR)/project-memory.ok
DOMAIN_CONTRACTS_STAMP := $(STAMP_DIR)/domain-contracts.ok

DEPS_INPUTS  := pyproject.toml
DEV_INPUTS   := pyproject.toml
PROJECT_MEMORY_INPUTS := pyproject.toml
DOMAIN_CONTRACTS_INPUTS := pyproject.toml

VERBOSE      ?= TRUE
LOG_OPTS     ?= -o log_cli=true -o log_cli_level=DEBUG

# =========================
# Help
# =========================
.PHONY: help
help: ## Show this help
	@echo "Available targets:"
	@grep -E '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) | sed -E 's/:.*?## /: /' | sort

# ============================================================
# Python / venv checks
# ============================================================
.PHONY: check-sys-python
check-sys-python: ## Sanity check on the system Python
	@command -v $(SYS_PY) >/dev/null 2>&1 || { \
		echo ""; \
		echo "System Python not found. Install Python 3.10+:"; \
		echo "  sudo apt install python3 python3-pip"; \
		echo ""; \
		exit 127; \
	}

.PHONY: check-pip
check-pip: ## Sanity check on the system pip
	@command -v $(SYS_PIP) >/dev/null 2>&1 || { \
		echo ""; \
		echo "pip not found. Install it:"; \
		echo "  sudo apt install python3-pip"; \
		echo ""; \
		exit 127; \
	}

.PHONY: check-venv-mod
check-venv-mod: check-sys-python ## Sanity check on the venv module
	@$(SYS_PY) -c "import venv" >/dev/null 2>&1 || { \
		echo ""; \
		echo "The 'venv' module is not available:"; \
		echo "  sudo apt install python3-venv"; \
		echo ""; \
		exit 127; \
	}

.PHONY: venv
venv: check-venv-mod ## Create the venv if needed
	@PY="$$(command -v python3 || command -v python)"; \
	test -x "$(VENV)/bin/python" || $$PY -m venv "$(VENV)"

.PHONY: ensure-pip
ensure-pip: venv ## Ensure pip in venv (robust, distro-safe)
	@tools/ensure_pip.sh "$(PYTHON)"

# ==================================
# Environment setup / dependencies
# ==================================
PIP_VERBOSE_FLAG := $(if $(VERBOSE),-v,)

$(DEPS_STAMP): $(DEPS_INPUTS) | ensure-pip
	@mkdir -p "$(STAMP_DIR)"
	@echo "Installing runtime deps..."
	@tools/pip_install_spec.sh -p "$(PYTHON)" -s . $(PIP_VERBOSE_FLAG)
	@touch "$(DEPS_STAMP)"

$(DEV_STAMP): $(DEPS_STAMP) $(DEV_INPUTS)
	@mkdir -p "$(STAMP_DIR)"
	@echo "Installing dev deps..."
	@tools/pip_install_spec.sh -p "$(PYTHON)" -s '.[dev]' -E $(PIP_VERBOSE_FLAG)
	@touch "$(DEV_STAMP)"

.PHONY: deps-dev
deps-dev: venv $(DEV_STAMP) ## Ensure dev deps installed (runs only when pyproject.toml changed)

.PHONY: setup
setup: $(DEV_STAMP) ## Install dev environment (same as deps-dev, convenience alias)

.PHONY: clean
clean: ## Remove caches and build artifacts
	rm -rf $(BUILD_DIR)/
	rm -rf dist build src/spreadsheet_handling.egg-info
	find $(ROOT) -type d -name '__pycache__' -prune -exec rm -rf {} +
	find $(ROOT) -type d -name '.pytest_cache' -prune -exec rm -rf {} +
	find $(ROOT) -name '.~lock.*#' -delete

.PHONY: clean-stamps
clean-stamps: ## Delete dependency stamps — forces reinstall on next make setup
	rm -rf $(STAMP_DIR)

.PHONY: clean-venv
clean-venv: clean-stamps ## Remove the virtualenv entirely
	rm -rf $(VENV)

.PHONY: distclean
distclean: clean clean-venv ## Deep clean: build artifacts + venv

# =========================
# Quality
# =========================
.PHONY: format
format: deps-dev ## Auto-fix with Ruff & Black
	$(RUFF) check src/spreadsheet_handling --fix
	$(BLACK) src/spreadsheet_handling

.PHONY: lint
lint: deps-dev ## Lint only (Ruff)
	$(RUFF) check src/spreadsheet_handling

.PHONY: source-style-guards
source-style-guards: deps-dev ## Run source-style guardrails separately from architecture guards
	$(PYTHON) tools/check_source_style.py

.PHONY: syntax
syntax: venv ## Syntax check
	$(PYTHON) -m compileall -q src/spreadsheet_handling

.PHONY: ci
ci: syntax lint test ## Run syntax + lint + tests

# =========================
# Docs (AsciiDoc → HTML/PDF)
# =========================
DOC_BUILD_DIR ?= target/docs
DOC_PAGES_DIR      := $(BUILD_DIR)/pages
DOC_PAGES_ROOT_DIR := $(BUILD_DIR)/pages-root
BUILD_DATE    := $(shell date -Iseconds)
DOCS_SRC      := $(wildcard docs/*/*.adoc)

.PHONY: docs-all docs-html docs-pages docs-pdf check-asciidoctor check-asciidoctor-plantuml check-plantuml check-graphviz check-asciidoctor-pdf clean-docs

docs-all: docs-html docs-pdf ## Build HTML and PDF for all docs/*/*.adoc

docs-pages: check-asciidoctor check-asciidoctor-plantuml check-plantuml check-graphviz ## Build public Pages HTML into build/pages/ and root nav into build/pages-root/
	@scripts/build_docs_pages.sh "$(DOC_PAGES_DIR)" "$(DOC_PAGES_ROOT_DIR)"

docs-html: check-asciidoctor ## Build HTML for all docs/*/*.adoc
	@set -e; \
	if [ -z "$(DOCS_SRC)" ]; then \
		echo "No docs found under docs/*/*.adoc"; \
	else \
		for src in $(DOCS_SRC); do \
			subdir="$$(dirname "$$src" | sed 's#^docs/##')"; \
			outdir="$(DOC_BUILD_DIR)/$$subdir"; \
			mkdir -p "$$outdir"; \
			outname="$$(basename "$$src" .adoc).html"; \
			asciidoctor \
				-a project-name="$(REPO)" \
				-a project-version="$(VER)" \
				-a build-rev="$(REV)" \
				-a build-date="$(BUILD_DATE)" \
				-D "$$outdir" \
				-o "$$outname" "$$src"; \
			echo "  $$src -> $$outdir/$$outname"; \
		done; \
	fi

docs-pdf: check-asciidoctor-pdf ## Build PDF for all docs/*/*.adoc
	@set -e; \
	if [ -z "$(DOCS_SRC)" ]; then \
		echo "No docs found under docs/*/*.adoc"; \
	else \
		for src in $(DOCS_SRC); do \
			subdir="$$(dirname "$$src" | sed 's#^docs/##')"; \
			outdir="$(DOC_BUILD_DIR)/$$subdir"; \
			mkdir -p "$$outdir"; \
			outname="$$(basename "$$src" .adoc).pdf"; \
			asciidoctor-pdf \
				-a project-name="$(REPO)" \
				-a project-version="$(VER)" \
				-a build-rev="$(REV)" \
				-a build-date="$(BUILD_DATE)" \
				-D "$$outdir" \
				-o "$$outname" "$$src"; \
			echo "  $$src -> $$outdir/$$outname"; \
		done; \
	fi

check-asciidoctor: ## Check asciidoctor is available
	@command -v asciidoctor >/dev/null 2>&1 || { \
		echo "asciidoctor not found. Install: sudo apt install asciidoctor"; \
		exit 127; \
	}

check-asciidoctor-plantuml: ## Check asciidoctor-plantuml Ruby extension is available
	@ruby -e 'require "asciidoctor-plantuml"' >/dev/null 2>&1 || { \
		echo "asciidoctor-plantuml not found. Install: sudo apt install ruby-asciidoctor-plantuml"; \
		exit 127; \
	}

check-plantuml: ## Check PlantUML is available for AsciiDoc diagrams
	@command -v plantuml >/dev/null 2>&1 || { \
		echo "plantuml not found. Install: sudo apt install plantuml"; \
		exit 127; \
	}

check-graphviz: ## Check Graphviz dot is available for diagram rendering
	@command -v dot >/dev/null 2>&1 || { \
		echo "graphviz dot not found. Install: sudo apt install graphviz"; \
		exit 127; \
	}

check-asciidoctor-pdf: check-asciidoctor ## Check asciidoctor-pdf is available
	@command -v asciidoctor-pdf >/dev/null 2>&1 || { \
		echo "asciidoctor-pdf not found. Install: gem install asciidoctor-pdf"; \
		exit 127; \
	}

clean-docs: ## Remove doc build output
	@rm -rf "$(DOC_BUILD_DIR)" "$(DOC_PAGES_DIR)" "$(DOC_PAGES_ROOT_DIR)"

# =========================
# Project memory
# =========================
.PHONY: memory-setup memory-export memory-query memory-context memory-extract memory-stage-extracted memory-refresh-workbook memory-import memory-check memory-promote memory-health-report
.PHONY: memory-export-ods memory-import-ods memory-diff-reimport memory-check-reimport memory-promote-reimport memory-promote-reimport-checked
.PHONY: check-memory-sheets-run

$(PROJECT_MEMORY_STAMP): $(PROJECT_MEMORY_INPUTS) | $(DEV_STAMP)
	@mkdir -p "$(STAMP_DIR)"
	@echo "Installing project_memory tooling deps..."
	@tools/pip_install_spec.sh -p "$(PYTHON)" -s '.[project-memory]' -E $(PIP_VERBOSE_FLAG)
	@$(PYTHON) -c "import jinja2"
	@touch "$(PROJECT_MEMORY_STAMP)"

memory-setup: $(PROJECT_MEMORY_STAMP) ## Install optional project_memory tooling in the shared local dev venv

check-memory-sheets-run: deps-dev ## Ensure the local sheets-run binary exists for project_memory targets
	@test -x "$(SHEETS_RUN)" || { \
		echo "sheets-run not found in $(VENV). Run 'make setup' or 'make memory-setup' first."; \
		exit 127; \
	}

memory-export: check-memory-sheets-run ## Render project_memory canonical JSON into project_memory.ods
	PYTHONPATH="$(ROOT):$(ROOT)src" $(SHEETS_RUN) --config "$(MEMORY_PIPELINE_DIR)/json_to_ods.yaml"

memory-query: check-memory-sheets-run ## Render derived project_memory query views into project_memory/derived
	@mkdir -p "$(MEMORY_DERIVED_DIR)"
	@find "$(MEMORY_DERIVED_DIR)" -mindepth 1 ! -name '.gitignore' -exec rm -rf {} +
	PYTHONPATH="$(ROOT):$(ROOT)src" $(SHEETS_RUN) --config "$(MEMORY_PIPELINE_DIR)/json_to_derived_queries.yaml"

memory-context: $(PROJECT_MEMORY_STAMP) memory-query ## Render the generated project_memory context report
	@mkdir -p "$(ROOT)docs_generated/project_memory"
	@find "$(ROOT)docs_generated/project_memory" -mindepth 1 ! -name '.gitignore' -exec rm -rf {} +
	PYTHONPATH="$(ROOT):$(ROOT)src" $(PYTHON) -m project_memory.plugins.render_context
	PYTHONPATH="$(ROOT):$(ROOT)src" $(PYTHON) -m project_memory.plugins.health_report
	@echo "$(ROOT)docs_generated/project_memory/current_context.adoc"

memory-health-report: ## Generate project_memory health report (derived diagnostic; requires memory-extract to have run)
	@mkdir -p "$(MEMORY_DERIVED_DIR)"
	PYTHONPATH="$(ROOT):$(ROOT)src" $(PYTHON) -m project_memory.plugins.health_report
	@echo "$(MEMORY_DERIVED_DIR)/memory_health_report.json"
	@echo "$(MEMORY_DERIVED_DIR)/memory_health_report.adoc"

memory-extract: check-memory-sheets-run ## Extract conservative project_memory candidates from ADOC artifacts
	@mkdir -p "$(MEMORY_DIR)/extracted"
	@find "$(MEMORY_DIR)/extracted" -mindepth 1 ! -name '.gitignore' -exec rm -rf {} +
	PYTHONPATH="$(ROOT):$(ROOT)src" $(PYTHON) -m project_memory.plugins.extract_candidates
	PYTHONPATH="$(ROOT):$(ROOT)src" $(PYTHON) -m project_memory.plugins.extract_commit_signals
	@echo "$(MEMORY_DIR)/extracted/"

memory-stage-extracted: ## Stage extracted candidates as generated ext_* canonical tables
	@set -euo pipefail; \
	src_dir="$(MEMORY_DIR)/extracted"; \
	dst_dir="$(MEMORY_CANONICAL_DIR)"; \
	test -d "$$src_dir" || { echo "Missing $$src_dir. Run 'make memory-extract' first." >&2; exit 1; }; \
	for name in finding_candidates.json ftr_candidates.json review_candidates.json; do \
		test -f "$$src_dir/$$name" || { echo "Missing extracted candidate file: $$src_dir/$$name. Run 'make memory-extract' first." >&2; exit 1; }; \
	done; \
	find "$$dst_dir" -maxdepth 1 -type f -name 'ext_*.json' -exec rm -f {} +; \
	for name in finding_candidates.json ftr_candidates.json review_candidates.json; do \
		cp -f "$$src_dir/$$name" "$$dst_dir/ext_$$name"; \
	done; \
	printf '%s\n' "$$dst_dir"/ext_finding_candidates.json "$$dst_dir"/ext_ftr_candidates.json "$$dst_dir"/ext_review_candidates.json

memory-refresh-workbook: ## Refresh project_memory.ods with current extracted candidate sheets
	$(MAKE) memory-extract
	$(MAKE) memory-stage-extracted
	$(MAKE) memory-export

memory-import: check-memory-sheets-run ## Reimport project_memory.ods into project_memory/staging
	@mkdir -p "$(MEMORY_STAGING_DIR)"
	@find "$(MEMORY_STAGING_DIR)" -mindepth 1 ! -name '.gitignore' -exec rm -rf {} +
	PYTHONPATH="$(ROOT):$(ROOT)src" $(SHEETS_RUN) --config "$(MEMORY_PIPELINE_DIR)/ods_to_json.yaml"

memory-check: memory-import memory-diff-reimport ## Reimport the ODS spreadsheet and compare it with canonical JSON

memory-diff-reimport: ## Compare canonical project_memory JSON with the current staging review area
	diff -ru --exclude='.gitignore' "$(MEMORY_CANONICAL_DIR)" "$(MEMORY_STAGING_DIR)"

memory-promote: ## Promote the current staging snapshot into canonical project_memory JSON
	@test -d "$(MEMORY_STAGING_DIR)" || (echo "Missing $(MEMORY_STAGING_DIR). Run memory-import or memory-check first." >&2; exit 1)
	cp -f "$(MEMORY_STAGING_DIR)"/*.json "$(MEMORY_CANONICAL_DIR)/"
	@test -f "$(MEMORY_STAGING_DIR)/_meta.yaml" && cp -f "$(MEMORY_STAGING_DIR)/_meta.yaml" "$(MEMORY_CANONICAL_DIR)/"

memory-check-reimport: memory-check
memory-promote-reimport: memory-promote
memory-promote-reimport-checked: memory-check memory-promote ## Reimport, compare, then promote the verified snapshot

# Backward-compatible aliases for the common typo in the target name.

# =========================
# Domain contracts
# =========================
.PHONY: domain-contracts-setup domain-contracts-check domain-contracts-context
.PHONY: domain-contracts-export domain-contracts-import domain-contracts-diff-reimport
.PHONY: domain-contracts-check-reimport domain-contracts-promote domain-contracts-promote-reimport-checked
.PHONY: check-domain-contracts-sheets-run

$(DOMAIN_CONTRACTS_STAMP): $(DOMAIN_CONTRACTS_INPUTS) | $(DEV_STAMP)
	@mkdir -p "$(STAMP_DIR)"
	@echo "Installing domain_contracts tooling deps..."
	@tools/pip_install_spec.sh -p "$(PYTHON)" -s . $(PIP_VERBOSE_FLAG)
	@touch "$(DOMAIN_CONTRACTS_STAMP)"

domain-contracts-setup: $(DOMAIN_CONTRACTS_STAMP) ## Install domain_contracts tooling in the shared local dev venv

check-domain-contracts-sheets-run: deps-dev ## Ensure the local sheets-run binary exists for domain-contracts targets
	@test -x "$(SHEETS_RUN)" || { \
		echo "sheets-run not found in $(VENV). Run 'make setup' or 'make domain-contracts-setup' first."; \
		exit 127; \
	}

domain-contracts-check: $(DOMAIN_CONTRACTS_STAMP) ## Validate canonical domain-contract JSON and write diagnostics
	@mkdir -p "$(DOMAIN_CONTRACTS_BUILD_DIR)"
	PYTHONPATH="$(ROOT)" $(PYTHON) -m tools.domain_contracts.check_contracts \
		--registry-dir "$(DOMAIN_CONTRACTS_CANONICAL_DIR)" \
		--report "$(DOMAIN_CONTRACTS_BUILD_DIR)/domain_contract_health.json"

domain-contracts-context: domain-contracts-check ## Validate and render generated domain-contract ADOC
	@mkdir -p "$(DOMAIN_CONTRACTS_GENERATED_DIR)"
	@find "$(DOMAIN_CONTRACTS_GENERATED_DIR)" -mindepth 1 ! -name '.gitignore' -exec rm -rf {} +
	PYTHONPATH="$(ROOT)" $(PYTHON) -m tools.domain_contracts.render_contracts \
		--registry-dir "$(DOMAIN_CONTRACTS_CANONICAL_DIR)" \
		--output "$(DOMAIN_CONTRACTS_GENERATED_DIR)/domain_contracts.adoc" \
		--report "$(DOMAIN_CONTRACTS_BUILD_DIR)/domain_contract_health.json"
	@echo "$(DOMAIN_CONTRACTS_GENERATED_DIR)/domain_contracts.adoc"

domain-contracts-export: check-domain-contracts-sheets-run ## Render domain-contract canonical JSON into an ODS workbook
	PYTHONPATH="$(ROOT):$(ROOT)src" $(SHEETS_RUN) --config "$(DOMAIN_CONTRACTS_PIPELINE_DIR)/json_to_ods.yaml"
	PYTHONPATH="$(ROOT)" $(PYTHON) -m tools.domain_contracts.promote_guard stamp \
		--canonical-dir "$(DOMAIN_CONTRACTS_CANONICAL_DIR)" \
		--workbook "$(DOMAIN_CONTRACTS_WORKBOOK)" \
		--out "$(DOMAIN_CONTRACTS_ODS_STAMP)"

domain-contracts-import: check-domain-contracts-sheets-run ## Reimport domain_contracts.ods into registries/domain_contracts/staging (refuses a workbook that does not match its export stamp)
	PYTHONPATH="$(ROOT):$(ROOT)src" $(PYTHON) -m tools.domain_contracts.promote_guard verify-workbook \
		--stamp "$(DOMAIN_CONTRACTS_ODS_STAMP)" \
		--workbook "$(DOMAIN_CONTRACTS_WORKBOOK)"
	@mkdir -p "$(DOMAIN_CONTRACTS_STAGING_DIR)"
	@find "$(DOMAIN_CONTRACTS_STAGING_DIR)" -mindepth 1 ! -name '.gitignore' -exec rm -rf {} +
	PYTHONPATH="$(ROOT):$(ROOT)src" $(SHEETS_RUN) --config "$(DOMAIN_CONTRACTS_PIPELINE_DIR)/ods_to_json.yaml"
	@cp -f "$(DOMAIN_CONTRACTS_ODS_STAMP)" "$(DOMAIN_CONTRACTS_STAGING_STAMP)"

domain-contracts-diff-reimport: ## Compare canonical domain-contract JSON with current staging
	diff -ru --exclude='.gitignore' --exclude='seeds' --exclude='.export_stamp.json' --exclude='_meta.yaml' "$(DOMAIN_CONTRACTS_CANONICAL_DIR)" "$(DOMAIN_CONTRACTS_STAGING_DIR)"

domain-contracts-check-reimport: domain-contracts-import domain-contracts-diff-reimport ## Reimport ODS and compare with canonical JSON

domain-contracts-promote: $(DOMAIN_CONTRACTS_STAMP) ## Promote current domain-contract staging snapshot into canonical JSON (gated: fresh + checker-valid staging only)
	@test -d "$(DOMAIN_CONTRACTS_STAGING_DIR)" || (echo "Missing $(DOMAIN_CONTRACTS_STAGING_DIR). Run domain-contracts-import or domain-contracts-check-reimport first." >&2; exit 1)
	PYTHONPATH="$(ROOT)" $(PYTHON) -m tools.domain_contracts.promote_guard verify \
		--canonical-dir "$(DOMAIN_CONTRACTS_CANONICAL_DIR)" \
		--stamp "$(DOMAIN_CONTRACTS_STAGING_STAMP)"
	@mkdir -p "$(DOMAIN_CONTRACTS_BUILD_DIR)"
	PYTHONPATH="$(ROOT)" $(PYTHON) -m tools.domain_contracts.check_contracts \
		--registry-dir "$(DOMAIN_CONTRACTS_STAGING_DIR)" \
		--report "$(DOMAIN_CONTRACTS_BUILD_DIR)/staging_domain_contract_health.json"
	cp -f "$(DOMAIN_CONTRACTS_STAGING_DIR)"/*.json "$(DOMAIN_CONTRACTS_CANONICAL_DIR)/"
	@test -f "$(DOMAIN_CONTRACTS_STAGING_DIR)/_meta.yaml" && cp -f "$(DOMAIN_CONTRACTS_STAGING_DIR)/_meta.yaml" "$(DOMAIN_CONTRACTS_CANONICAL_DIR)/" || true

domain-contracts-promote-reimport-checked: domain-contracts-check-reimport domain-contracts-promote ## Reimport, compare, then promote verified domain-contract JSON

# =========================
# Snapshot
# =========================
.PHONY: snapshot
snapshot: ## Create a repository text snapshot (excludes build/, venv, binaries)
	@mkdir -p "$(BUILD_DIR)"
	@bash "$(ROOT)tools/repo_snapshot.sh" "$(ROOT)" "$(BUILD_DIR)" "$(BUILD_DIR)/spreadsheet-handling.txt"
	@echo "Snapshot: $(BUILD_DIR)/spreadsheet-handling.txt"

.PHONY: snapshot-multi
snapshot-multi: ## Create split snapshots; merge smallest files down to SNAPSHOT_MAX_FILES (default 20)
	@mkdir -p "$(BUILD_DIR)"
	@bash "$(ROOT)tools/repo_snapshot_multi.sh" "$(ROOT)" "$(BUILD_DIR)/snapshots"
	@bash "$(ROOT)scripts/merge_snapshots.sh" "$(BUILD_DIR)/snapshots" "$(SNAPSHOT_MAX_FILES)"
	@echo "Multi-snapshots written to $(BUILD_DIR)/snapshots/ (max $(SNAPSHOT_MAX_FILES) files)"

# =========================
# Release helpers
# =========================
.PHONY: release-check
release-check: ## Pre-tag branch and topology check (read-only). Pass a tag as TAG=vX.Y.Z to also validate the tag.
	@bash "$(ROOT)tools/release_check.sh" "$(TAG)"

.PHONY: pages-check
pages-check: ## Post-deploy Pages structure check. CORE_TAG=vX required; DEMO_TAG, PAGES_DIR optional; LATEST=1 also checks latest/ aliases.
	@bash "$(ROOT)tools/pages_publish_check.sh" \
	  $(if $(PAGES_DIR),--pages "$(PAGES_DIR)") \
	  $(if $(CORE_TAG),--core-tag "$(CORE_TAG)") \
	  $(if $(DEMO_TAG),--demo-tag "$(DEMO_TAG)") \
	  $(if $(LATEST),--check-latest)

.PHONY: readme-check
readme-check: ## Pre-publish README link-versioning check. TAG=vX.Y.Z enforces /versions/<tag>/ (fails on remaining /latest/ Pages URLs); without TAG runs lint mode. FILE=PATH overrides ./README.md.
	@bash "$(ROOT)tools/readme_links_check.sh" \
	  $(if $(TAG),--release-tag "$(TAG)") \
	  $(if $(FILE),--file "$(FILE)")

.PHONY: release-status
release-status: ## One-shot cross-repo release state (core/demo/pages). CORE_DIR/DEMO_DIR/PAGES_DIR optional (siblings auto-detected).
	@bash "$(ROOT)tools/release_status.sh" \
	  $(if $(CORE_DIR),--core "$(CORE_DIR)") \
	  $(if $(DEMO_DIR),--demo "$(DEMO_DIR)") \
	  $(if $(PAGES_DIR),--pages "$(PAGES_DIR)")

# =========================
# Domain reformation helpers
# =========================
.PHONY: reformation-slice reformation-check reformation-driver

reformation-slice: ## Scaffold a domain reformation slice. Usage: make reformation-slice NAME=fk-helper-unresolved-values
	@test -n "$(NAME)" || { echo "NAME is required, e.g. make reformation-slice NAME=fk-helper-unresolved-values" >&2; exit 2; }
	@bash "$(ROOT)scripts/reformation_slice.sh" create "$(NAME)"

reformation-check: ## Check a domain reformation slice. Usage: make reformation-check SLICE=fk-helper-unresolved-values
	@test -n "$(SLICE)" || { echo "SLICE is required, e.g. make reformation-check SLICE=fk-helper-unresolved-values" >&2; exit 2; }
	@bash "$(ROOT)scripts/reformation_slice.sh" check "$(SLICE)"

reformation-driver: ## Print a reusable agent driver prompt. Usage: make reformation-driver SLICE=fk-helper-unresolved-values
	@test -n "$(SLICE)" || { echo "SLICE is required, e.g. make reformation-driver SLICE=fk-helper-unresolved-values" >&2; exit 2; }
	@bash "$(ROOT)scripts/reformation_slice.sh" driver "$(SLICE)" \
	  $(foreach source,$(SOURCES),--source "$(source)") \
	  $(foreach hint,$(TEST_HINTS),--test-hint "$(hint)")

# =========================
# Coverage
# =========================
.PHONY: coverage coverage-html

coverage: deps-dev ## Coverage report in terminal (with missing lines)
	@mkdir -p $(BUILD_DIR)
	COVERAGE_FILE=$(COV_DATA) $(PYTEST) \
		-s $(MARK_OPT) $(LOG_OPTS) \
		--cov=src/spreadsheet_handling \
		--cov-report=term-missing \
		$(ACTIVE_TEST_PATHS)

coverage-html: deps-dev ## Coverage as HTML report (build/htmlcov/)
	@mkdir -p $(COV_HTML_DIR)
	COVERAGE_FILE=$(COV_DATA) $(PYTEST) \
		-s $(MARK_OPT) $(LOG_OPTS) \
		--cov=src/spreadsheet_handling \
		--cov-report=html:$(COV_HTML_DIR) \
		$(ACTIVE_TEST_PATHS)
	@echo "Open: file://$(COV_HTML_DIR)/index.html"

# =========================
# Tests
# =========================
# Quick reference:
#   make test                              # unit + integ + roundtrip + arch, no slow/prehex
#   make test-fast                         # unit only (fastest feedback)
#   make test-arch                         # architecture / guardrail layer
#   make test-full                         # everything including slow tests
#   make test-one TESTPATTERN="xlookup"    # filter by keyword
#   make test-file FILE=tests/unit/...     # single file
#   make test-node NODE=tests/unit/..::fn  # single test

.PHONY: test test-fast test-unit test-integ test-roundtrip test-arch test-full \
        test-verbose test-lastfailed test-one test-file test-node

MARK              ?= not legacy and not prehex and not slow
PYTEST_OPTS       ?=
ACTIVE_TEST_PATHS ?= tests/unit tests/integration tests/roundtrip tests/architecture

MARK_OPT := $(if $(strip $(MARK)),-m '$(MARK)',)

define run_pytest
	$(PYTEST) $(MARK_OPT) $(PYTEST_OPTS) $(1)
endef

test: deps-dev ## Active suite: unit + integ + roundtrip + arch (no slow/prehex)
	$(call run_pytest,$(ACTIVE_TEST_PATHS))

test-fast: deps-dev ## Unit tests only — fastest feedback loop
	$(PYTEST) -q $(MARK_OPT) $(PYTEST_OPTS) tests/unit

test-unit: deps-dev ## Unit tests only
	$(PYTEST) -q $(MARK_OPT) $(PYTEST_OPTS) tests/unit

test-integ: deps-dev ## Integration tests only
	$(PYTEST) -q $(MARK_OPT) $(PYTEST_OPTS) tests/integration

test-arch: deps-dev ## Architecture and guardrail tests only
	$(PYTEST) -q $(MARK_OPT) $(PYTEST_OPTS) tests/architecture

test-roundtrip: deps-dev ## Roundtrip invariant tests only (FTR-ROUNDTRIP-TEST-LAYER-P4A)
	$(PYTEST) -q $(MARK_OPT) $(PYTEST_OPTS) tests/roundtrip

test-full: deps-dev ## All tests including slow (no marker filter)
	$(PYTEST) -q $(PYTEST_OPTS) $(ACTIVE_TEST_PATHS)

test-verbose: deps-dev ## Run active suite with inline logs
	SHEETS_LOG=INFO $(PYTEST) -vv -s $(MARK_OPT) $(PYTEST_OPTS) $(ACTIVE_TEST_PATHS)

test-lastfailed: deps-dev ## Re-run only last failed tests
	SHEETS_LOG=DEBUG $(PYTEST) --lf -vv $(MARK_OPT) $(PYTEST_OPTS) $(ACTIVE_TEST_PATHS)

test-one: deps-dev ## Filter by keyword: make test-one TESTPATTERN="xlookup"
	@if [ -z "$(TESTPATTERN)" ]; then echo "Set TESTPATTERN=..."; exit 2; fi
	SHEETS_LOG=DEBUG $(PYTEST) -vv -k '$(TESTPATTERN)' $(MARK_OPT) $(PYTEST_OPTS) $(ACTIVE_TEST_PATHS)

test-file: deps-dev ## Single file: make test-file FILE=tests/unit/...
	@if [ -z "$(FILE)" ]; then echo "Set FILE=path/to/test_file.py"; exit 2; fi
	$(PYTEST) -vv $(PYTEST_OPTS) $(FILE)

test-node: deps-dev ## Single test: make test-node NODE=tests/unit/...::fn
	@if [ -z "$(NODE)" ]; then echo "Set NODE=file::test_name"; exit 2; fi
	$(PYTEST) -vv $(PYTEST_OPTS) $(NODE)

# =========================
# Diagnose
# =========================
.PHONY: doctor
doctor: ## Show environment and stamp state
	@echo "VENV:      $(VENV)  (exists? $$([ -d $(VENV) ] && echo yes || echo no))"
	@echo "STAMP_DIR: $(STAMP_DIR)"
	@echo "DEPS:      $(DEPS_STAMP)  (exists? $$([ -f $(DEPS_STAMP) ] && echo yes || echo no))"
	@echo "DEV:       $(DEV_STAMP)   (exists? $$([ -f $(DEV_STAMP) ] && echo yes || echo no))"
	@echo "PYPROJECT: pyproject.toml"
