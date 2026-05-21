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

STAMP_DIR    := $(VENV)/.stamp
DEPS_STAMP   := $(STAMP_DIR)/deps
DEV_STAMP    := $(STAMP_DIR)/dev

DEPS_INPUTS  := pyproject.toml
DEV_INPUTS   := pyproject.toml

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
# Snapshot
# =========================
.PHONY: snapshot
snapshot: ## Create a repository text snapshot (excludes build/, venv, binaries)
	@mkdir -p "$(BUILD_DIR)"
	@bash "$(ROOT)tools/repo_snapshot.sh" "$(ROOT)" "$(BUILD_DIR)" "$(BUILD_DIR)/spreadsheet-handling.txt"
	@echo "Snapshot: $(BUILD_DIR)/spreadsheet-handling.txt"

.PHONY: snapshot-multi
snapshot-multi: ## Create split snapshots per section in build/snapshots/ (docs, src, tests, infra, tree, loc)
	@mkdir -p "$(BUILD_DIR)"
	@bash "$(ROOT)tools/repo_snapshot_multi.sh" "$(ROOT)" "$(BUILD_DIR)/snapshots"
	@echo "Multi-snapshots written to $(BUILD_DIR)/snapshots/"

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
#   make test                              # unit + integ + arch, no slow/prehex
#   make test-fast                         # unit only (fastest feedback)
#   make test-arch                         # architecture / guardrail layer
#   make test-full                         # everything including slow tests
#   make test-one TESTPATTERN="xlookup"    # filter by keyword
#   make test-file FILE=tests/unit/...     # single file
#   make test-node NODE=tests/unit/..::fn  # single test

.PHONY: test test-fast test-unit test-integ test-arch test-full \
        test-verbose test-lastfailed test-one test-file test-node

MARK              ?= not legacy and not prehex and not slow
PYTEST_OPTS       ?=
ACTIVE_TEST_PATHS ?= tests/unit tests/integration tests/architecture

MARK_OPT := $(if $(strip $(MARK)),-m '$(MARK)',)

define run_pytest
	$(PYTEST) $(MARK_OPT) $(PYTEST_OPTS) $(1)
endef

test: deps-dev ## Active suite: unit + integ + arch (no slow/prehex)
	$(call run_pytest,$(ACTIVE_TEST_PATHS))

test-fast: deps-dev ## Unit tests only — fastest feedback loop
	$(PYTEST) -q $(MARK_OPT) $(PYTEST_OPTS) tests/unit

test-unit: deps-dev ## Unit tests only
	$(PYTEST) -q $(MARK_OPT) $(PYTEST_OPTS) tests/unit

test-integ: deps-dev ## Integration tests only
	$(PYTEST) -q $(MARK_OPT) $(PYTEST_OPTS) tests/integration

test-arch: deps-dev ## Architecture and guardrail tests only
	$(PYTEST) -q $(MARK_OPT) $(PYTEST_OPTS) tests/architecture

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
# Demo run
# =========================
.PHONY: run
run: deps-dev ## Demo: roundtrip on example
	$(VENV)/bin/sheets-pack \
	  examples/roundtrip_start.json \
	  -o $(BUILD_DIR)/demo.xlsx \
	  --levels 3
	$(VENV)/bin/sheets-unpack \
	  $(BUILD_DIR)/demo.xlsx \
	  -o $(BUILD_DIR)/demo_out \
	  --levels 3

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
