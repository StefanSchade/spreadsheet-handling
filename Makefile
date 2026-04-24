# =========================
# Project variables
# =========================
REPO ?= spreadsheet-handling
VER  ?= 0.0.0                           # retrieve from git later on
REV  ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo "nogit")

SHELL 		 := /usr/bin/env bash
.SHELLFLAGS  := -eu -o pipefail -c

REPO := $(shell git rev-parse --show-toplevel 2>/dev/null | xargs basename)
VER  := $(shell git describe --tags --always --dirty 2>/dev/null || echo DEV-SNAPSHOT)
REV  := $(shell git rev-parse --short HEAD 2>/dev/null || echo local)
DATE := $(shell date -Iseconds)

ROOT          := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
BUILD_DIR     := $(ROOT)build
TARGET_DIR    := $(ROOT)target
DOC_BUILD_DIR := $(BUILD_DIR)/doc
VENV          := $(ROOT).venv
COV_HTML_DIR  := $(BUILD_DIR)/htmlcov
COV_DATA      := $(BUILD_DIR)/.coverage

# System Python executables
SYS_PY       ?= python3
SYS_PIP      ?= pip3

# VENV Python executables
PYTHON       := $(VENV)/bin/python
PYTEST       := $(VENV)/bin/pytest
RUFF         := $(VENV)/bin/ruff
BLACK        := $(VENV)/bin/black

STAMP_DIR    := $(VENV)/.stamp
DEPS_STAMP     := $(STAMP_DIR)/deps
DEV_STAMP    := $(STAMP_DIR)/dev

PYPROJECT    := $(ROOT)pyproject.toml

# pyproject is single source of truth
DEPS_INPUTS := pyproject.toml
DEV_INPUTS  := pyproject.toml

VERBOSE      ?= TRUE

# pytest logging options for debug runs
LOG_OPTS  ?= -o log_cli=true -o log_cli_level=DEBUG

# =========================
# Phony targets
# =========================
.PHONY: test test-verbose test-lastfailed test-one test-file test-node \
        coverage coverage-html run snapshot doctor \
        check-sys-python check-pip

# =========================
# Help (auto)
# =========================
help: ## Show this help
	@echo "Available targets:"
	@grep -E '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) | sed -E 's/:.*?## /: /' | sort

# ============================================================
#  checks for Python / pip / venv availability
# ============================================================
.PHONY: check-sys-python
check-sys-python: ## Sanity check on the system Python
	@command -v $(SYS_PY) >/dev/null 2>&1 || { \
		echo ""; \
		echo "❌  System Python was not found on your PATH."; \
		echo "    Please install Python 3.10+ and ensure 'python3' or 'python' is available."; \
		echo "    For example:"; \
		echo "      sudo apt install python3 python3-pip"; \
		echo "      or see https://www.python.org/downloads/"; \
		echo ""; \
		exit 127; \
	}

.PHONY: check-pip
check-pip: ##  Sanity check on the system pip
	@command -v $(SYS_PIP ) >/dev/null 2>&1 || { \
		echo ""; \
		echo "❌  pip was not found on your PATH."; \
		echo "    Please install pip for Python 3."; \
		echo "    For example:"; \
		echo "      sudo apt install python3-pip"; \
		echo "      or see https://pip.pypa.io/en/stable/installation/"; \
		echo ""; \
		exit 127; \
	}

.PHONY: check-venv-mod
check-venv-mod: check-sys-python ## Sanity check on the venv module
	@$(SYS_PY) -c "import venv" >/dev/null 2>&1 || { \
		echo ""; \
		echo "❌  The 'venv' module is not available in your Python."; \
		echo "    On Ubuntu/WSL install it with:"; \
		echo "      sudo apt install python3-venv"; \
		echo ""; \
		exit 127; \
	}

.PHONY: venv
venv: check-venv-mod ## Create the venv if needed
	@if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then \
	  echo "❌ Python not found. Install Python 3.x."; exit 2; fi
	@PY="$$(command -v python3 || command -v python)"; \
	test -x "$(VENV)/bin/python" || $$PY -m venv "$(VENV)"

.PHONY: ensure-pip
ensure-pip: venv ## Ensure pip in venv (robust, distro-safe)
	@tools/ensure_pip.sh "$(PYTHON)"

# ==================================
# Project Environment & dependencies
# ==================================
PIP_VERBOSE_FLAG := $(if $(VERBOSE),-v,)

$(DEPS_STAMP): $(DEPS_INPUTS) | ensure-pip ## install python runtime dependencies non editable
	@mkdir -p "$(STAMP_DIR)"
	@echo "➡️  Installing runtime (editable) only when inputs changed..."
	@tools/pip_install_spec.sh -p "$(PYTHON)" -s . $(PIP_VERBOSE_FLAG)
	@touch "$(DEPS_STAMP)"

$(DEV_STAMP): $(DEPS_STAMP) $(DEV_INPUTS) ## install python dev dependencies editable
	@mkdir -p "$(STAMP_DIR)"
	@echo "➡️  Installing dev extras only when inputs changed..."
	@tools/pip_install_spec.sh -p "$(PYTHON)" -s '.[dev]' -E $(PIP_VERBOSE_FLAG)
	@touch "$(DEV_STAMP)"

deps-dev: venv $(DEV_STAMP) ## Ensure dev deps installed

.PHONY: setup
setup: $(DEV_STAMP)  ## Convenient target to install dev and runtime incl. dependencies

.PHONY: reset-deps
reset-deps: ## Force reinstall deps (deletes stamps) as a workaround for WSL
	@rm -f $(DEPS_STAMP) $(DEV_STAMP)

clean: ## Remove caches and build artifacts
	rm -rf $(BUILD_DIR)/
	rm -rf dist build src/spreadsheet_handling.egg-info
	find $(ROOT) -type d -name '__pycache__' -prune -exec rm -rf {} +
	find $(ROOT) -type d -name '.pytest_cache' -prune -exec rm -rf {} +
	find $(ROOT) -name '.~lock.*#' -delete

.PHONY: clean-stamps
clean-stamps: ## Remove dependency stamps (forces re-install on next run)
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

.PHONY: syntax
syntax: venv ## Syntax check
	$(PYTHON) -m compileall -q src/spreadsheet_handling

.PHONY: ci
ci: syntax lint test ## Run syntax + lint + tests

# =========================
# Docs (AsciiDoc → HTML/PDF)
# =========================
DOC_BUILD_DIR ?= target/docs
BUILD_DATE := $(shell date -Iseconds)

# All .adoc files two levels under docs/
DOCS_SRC := $(wildcard docs/*/*.adoc)

.PHONY: docs-user docs-html docs-pdf check-asciidoctor check-asciidoctor-pdf clean-docs

.PHONY: docs-all
docs-all: docs-html docs-pdf ## build html and pdf for all 2-level docs

.PHONY: docs-html
docs-html: check-asciidoctor ## build HTML for all docs/*/*.adoc
	@set -e; \
	if [ -z "$(DOCS_SRC)" ]; then \
		echo "ℹ️  No docs found under docs/*/*.adoc"; \
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
			echo "• $$src  →  $$outdir/$$outname"; \
		done; \
		echo "✅ HTML docs written to $(DOC_BUILD_DIR)"; \
	fi

.PHONY: docs-pdf
docs-pdf: check-asciidoctor-pdf ## Build PDF for all docs/*/*.adoc
	@set -e; \
	if [ -z "$(DOCS_SRC)" ]; then \
		echo "ℹ️  No docs found under docs/*/*.adoc"; \
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
			echo "• $$src  →  $$outdir/$$outname"; \
		done; \
		echo "✅ PDF docs written to $(DOC_BUILD_DIR)"; \
	fi

.PHONY: check-asciidoctor
check-asciidoctor: ## Sanity check asciidocutor
	@command -v asciidoctor >/dev/null 2>&1 || { \
		echo ""; \
		echo "❌  'asciidoctor' not found on PATH."; \
		echo "    Install it, e.g.:"; \
		echo "      # Ubuntu"; \
		echo "      sudo apt install asciidoctor"; \
		echo "      # macOS (Homebrew)"; \
		echo "      brew install asciidoctor"; \
		echo ""; \
		exit 127; \
	}

.PHONY: check-asciidoctor-pdf
check-asciidoctor-pdf: check-asciidoctor ## Sanity check asciidoctor-pdf
	@command -v asciidoctor-pdf >/dev/null 2>&1 || { \
		echo ""; \
		echo "❌  'asciidoctor-pdf' not found on PATH."; \
		echo "    Install it, e.g.:"; \
		echo "      # RubyGems"; \
		echo "      gem install asciidoctor-pdf"; \
		echo "      # Ubuntu (may be in universe)"; \
		echo "      sudo apt install ruby-asciidoctor-pdf || gem install asciidoctor-pdf"; \
		echo "      # macOS"; \
		echo "      gem install asciidoctor-pdf"; \
		echo ""; \
		exit 127; \
	}

.PHONY: clean-docs
clean-docs:
	@rm -rf "$(DOC_BUILD_DIR)"
	@echo "🧹 Docs cleaned (removed $(DOC_BUILD_DIR))"

# =========================
# Snapshot
# =========================

.PHONY: snapshot
snapshot: ## Create a repository text snapshot (excludes build/, venv, binaries, etc.)
	@echo "➡️  Creating repository snapshot..."
	mkdir -p "$(BUILD_DIR)"
	@# Call the outer script which delegates to concat_files_core.sh
	@bash "$(ROOT)tools/repo_snapshot.sh" "$(ROOT)" "$(BUILD_DIR)" "$(BUILD_DIR)/spreadsheet-handling.txt"
	@echo "✅  Snapshot written to $(BUILD_DIR)/spreadsheet-handling.txt"


# =========================
# Coverage
# =========================
.PHONY: coverage
coverage: deps-dev ## Coverage in terminal (with missing lines)
	mkdir -p $(BUILD_DIR)
	COVERAGE_FILE=$(COV_DATA) $(PYTEST) \
		-s $(MARK_OPT) $(LOG_OPTS) \
		--cov=src/spreadsheet_handling \
		--cov-report=term-missing \
		$(ACTIVE_TEST_PATHS)

.PHONY: coverage-html
coverage-html: deps-dev ## Coverage as HTML report (build/htmlcov/)
	mkdir -p $(COV_HTML_DIR)
	COVERAGE_FILE=$(COV_DATA) $(PYTEST) \
		-s $(MARK_OPT) $(LOG_OPTS) \
		--cov=src/spreadsheet_handling \
		--cov-report=html:$(COV_HTML_DIR) \
		$(ACTIVE_TEST_PATHS)
	@echo "Open HTML report: file://$(COV_HTML_DIR)/index.html"

# ================================
# How to run the test suite
# ================================
#
# Defaults:
# - `make test` runs the active suite with `not legacy and not prehex and not slow`
# - Physical placement remains primary; markers provide focused execution slices
# - Use `make test-all` to include slow tests across the active suite
#
# Common:
#   make test                          # active development slice
#   make test MARK=                    # same paths, no marker filter
#   make test MARK="not legacy and not prehex"  # include slow tests
#   make test-verbose                  # verbose, stream logs
#   make test-lastfailed               # re-run last failed
#
# Slices:
#   make test-unit                     # unit only
#   make test-integ                    # integration only
#   make test-arch                     # architecture / guardrail layer only
#   make test-ir                       # XLSX IR-focused slice
#   make test-ods                      # ODS / Calc-focused slice
#   make test-smoke                    # smoke checks
#   make test-prehex                   # explicit quarantined pre-hex slice
#   make test-all                      # all active tests, including slow tests
#
# Focus:
#   make test-one TESTPATTERN="foo and not slow"
#   make test-file FILE=tests/unit/pipeline/test_runner.py
#   make test-node NODE=tests/unit/pipeline/test_runner.py::test_happy_path
#
# Notes:
# - Override MARK when you need a custom marker slice on the active topology.
# - `test-prehex` is explicit and may report a deferred/no-tests outcome when empty.
# - By default we use the venv's pytest if available: $(VENV)/bin/pytest

# =========================
# Test targets
# =========================
.PHONY: test test-verbose test-lastfailed test-one test-file test-node \
        test-unit test-integ test-arch test-ir test-ods test-smoke \
        test-prehex test-legacy test-legacy-try test-all

# Venv + pytest resolution
VENV         ?= .venv
PYTEST       ?= $(if $(wildcard $(VENV)/bin/pytest),$(VENV)/bin/pytest,pytest)

# Default filters and knobs
MARK         ?= not legacy and not prehex and not slow
PYTEST_OPTS  ?=
ACTIVE_TEST_PATHS ?= tests/unit tests/integration tests/architecture
PREHEX_DIR   ?= tests/legacy_pre_hex

# Apply -m only if MARK is set
MARK_OPT     := $(if $(strip $(MARK)),-m '$(MARK)',)

# Helper macro
define run_pytest
	$(PYTEST) $(MARK_OPT) $(PYTEST_OPTS) $(1)
endef

# ---- Targets (with ## help comments) ----

test: deps-dev ## Run the normal active development slice
	$(call run_pytest,$(ACTIVE_TEST_PATHS))

test-verbose: deps-dev ## Verbose run with inline logs
	SHEETS_LOG=INFO $(PYTEST) -vv -s $(MARK_OPT) $(PYTEST_OPTS) $(ACTIVE_TEST_PATHS)

test-lastfailed: deps-dev ## Re-run only last failed tests (verbose)
	SHEETS_LOG=DEBUG $(PYTEST) --lf -vv $(MARK_OPT) $(PYTEST_OPTS) $(ACTIVE_TEST_PATHS)

test-one: deps-dev ## Run tests filtered by TESTPATTERN (make test-one TESTPATTERN="expr")
	@if [ -z "$(TESTPATTERN)" ]; then echo "Set TESTPATTERN=..."; exit 2; fi
	SHEETS_LOG=DEBUG $(PYTEST) -vv -k '$(TESTPATTERN)' $(MARK_OPT) $(PYTEST_OPTS) $(ACTIVE_TEST_PATHS)

test-file: deps-dev ## Run a single test file (make test-file FILE=path/to/test_file.py)
	@if [ -z "$(FILE)" ]; then echo "Set FILE=path/to/test_file.py"; exit 2; fi
	$(PYTEST) -vv $(MARK_OPT) $(PYTEST_OPTS) $(FILE)

test-node: deps-dev ## Run a single test node (make test-node NODE=file::test_name)
	@if [ -z "$(NODE)" ]; then echo "Set NODE=file::test_name"; exit 2; fi
	$(PYTEST) -vv $(MARK_OPT) $(PYTEST_OPTS) $(NODE)

test-unit: deps-dev ## Unit tests only
	$(PYTEST) -q $(MARK_OPT) $(PYTEST_OPTS) tests/unit

test-integ: deps-dev ## Integration tests only
	$(PYTEST) -q $(MARK_OPT) $(PYTEST_OPTS) tests/integration

test-arch: deps-dev ## Architecture and guardrail tests only
	$(PYTEST) -q $(MARK_OPT) $(PYTEST_OPTS) tests/architecture

test-ir: deps-dev ## XLSX IR-focused tests
	$(PYTEST) -q -m 'xlsx_ir and not slow and not legacy and not prehex' $(PYTEST_OPTS) $(ACTIVE_TEST_PATHS)

test-ods: deps-dev ## ODS / Calc-focused tests
	$(PYTEST) -q -m 'ods and not slow and not legacy and not prehex' $(PYTEST_OPTS) $(ACTIVE_TEST_PATHS)

test-smoke: deps-dev ## Smoke checks only
	$(PYTEST) -q -m 'smoke and not slow and not legacy and not prehex' $(PYTEST_OPTS) $(ACTIVE_TEST_PATHS)

test-all: deps-dev ## Run all active tests, including slow tests
	$(PYTEST) -q $(PYTEST_OPTS) $(ACTIVE_TEST_PATHS)

test-prehex: deps-dev ## Explicit quarantined pre-hex slice (or deferred when empty)
	@if find "$(PREHEX_DIR)" -type f -name 'test_*.py' | grep -q .; then \
		RUN_PREHEX=1 $(PYTEST) -q $(PYTEST_OPTS) "$(PREHEX_DIR)"; \
	else \
		echo "No pre-hex test files present under $(PREHEX_DIR); target currently deferred."; \
	fi

# Backward-compatible aliases for the explicit pre-hex slice
test-legacy: test-prehex ## Backward-compatible alias for the explicit pre-hex slice
	@:

# Alias retained for older local workflows and docs
test-legacy-try: test-prehex ## Backward-compatible alias for the explicit pre-hex slice
	@:

# =========================
# Demo run
# =========================

run: deps ## Demo: roundtrip on example
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
doctor: ## Show env + stamps (kleines Diagnose-Target)
	@echo "VENV:      $(VENV)  (exists? $$([ -d $(VENV) ] && echo yes || echo no))"
	@echo "STAMP_DIR: $(STAMP_DIR)"
	@echo "DEPS:      $(DEPS_STAMP)  (exists? $$([ -f $(DEPS_STAMP) ] && echo yes || echo no))"
	@echo "DEV:       $(DEV_STAMP)   (exists? $$([ -f $(DEV_STAMP) ] && echo yes || echo no))"
	@echo "PYPROJECT: $(PYPROJECT)"
