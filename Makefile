# =========================
# Project variables
# =========================
SHELL 		 := /usr/bin/env bash
.SHELLFLAGS  := -eu -o pipefail -c

ROOT         := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
TARGET       := $(ROOT)build
VENV         := $(ROOT).venv
COV_HTML_DIR := $(TARGET)/htmlcov
COV_DATA     := $(TARGET)/.coverage

PYTHON       := $(VENV)/bin/python
PYTEST       := $(VENV)/bin/pytest
RUFF         := $(VENV)/bin/ruff
BLACK        := $(VENV)/bin/black

STAMP_DIR    := $(VENV)/.stamp
DEPS_STAMP   := $(STAMP_DIR)/deps
DEV_STAMP    := $(STAMP_DIR)/dev

PYPROJECT    := $(ROOT)pyproject.toml

# pytest logging options for debug runs
LOG_OPTS  ?= -o log_cli=true -o log_cli_level=DEBUG

# =========================
# Phony targets
# =========================
.PHONY: help setup reset-deps clean clean-stamps clean-venv distclean venv \
        test test-verbose test-lastfailed test-one test-file test-node \
        format lint syntax ci coverage coverage-html run snapshot doctor

# =========================
# Help (auto)
# =========================
help: ## Show this help
	@echo "Available targets:"
	@grep -E '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) | sed -E 's/:.*?## /: /' | sort

# =========================
# Environment & dependencies
# =========================
venv: ## Create .venv if missing
	@test -d $(VENV) || python3 -m venv $(VENV)

# Runtime deps + editable install of the package
$(DEPS_STAMP): | venv ## Call 'make reset-deps' if pyproject changes (WSL workaround)
	$(PYTHON) -m pip install -e .
	@mkdir -p $(STAMP_DIR)
	@touch $(DEPS_STAMP)

deps: $(DEPS_STAMP) ## Ensure runtime deps installed

# Dev tools (ruff/black/pytest/pytest-cov/pyyaml) via extras
$(DEV_STAMP): $(DEPS_STAMP) ## Call 'make reset-deps' if pyproject changes (WSL workaround)
	$(PYTHON) -m pip install -e '.[dev]'
	@mkdir -p $(STAMP_DIR)
	@touch $(DEV_STAMP)

deps-dev: venv $(DEV_STAMP) ## Ensure dev deps installed

setup: deps-dev ## One-shot: create venv + install runtime & dev deps

reset-deps: ## Force reinstall deps (deletes stamps)
	@rm -f $(DEPS_STAMP) $(DEV_STAMP)

clean: ## Remove caches and build artifacts
	rm -rf $(TARGET)/
	rm -rf dist build src/spreadsheet_handling.egg-info
	find $(ROOT) -type d -name '__pycache__' -prune -exec rm -rf {} +
	find $(ROOT) -type d -name '.pytest_cache' -prune -exec rm -rf {} +
	find $(ROOT) -name '.~lock.*#' -delete

clean-stamps: ## Remove dependency stamps (forces re-install on next run)
	rm -rf $(STAMP_DIR)

clean-venv: clean-stamps ## Remove the virtualenv entirely
	rm -rf $(VENV)

distclean: clean clean-venv ## Deep clean: build artifacts + venv

# =========================
# Quality
# =========================
format: deps-dev ## Auto-fix with Ruff & Black
	$(RUFF) check src/spreadsheet_handling --fix
	$(BLACK) src/spreadsheet_handling

lint: deps-dev ## Lint only (Ruff)
	$(RUFF) check src/spreadsheet_handling

syntax: venv ## Syntax check
	$(PYTHON) -m compileall -q src/spreadsheet_handling

ci: syntax lint test ## Run syntax + lint + tests


# =========================
# Snapshot
# =========================
snapshot: ## Repo snapshot under build/
	mkdir -p $(TARGET)
	$(ROOT)tools/repo_snapshot.sh $(ROOT) $(TARGET) $(TARGET)/repo.txt

# =========================
# Coverage
# =========================
coverage: deps-dev ## Coverage in terminal (with missing lines)
	mkdir -p $(TARGET)
	COVERAGE_FILE=$(COV_DATA) $(PYTHON) -m pytest \
		--cov=src/spreadsheet_handling \
		--cov-report=term-missing \
		tests

coverage-html: deps-dev ## Coverage as HTML report (build/htmlcov/)
	mkdir -p $(COV_HTML_DIR)
	COVERAGE_FILE=$(COV_DATA) $(PYTHON) -m pytest \
		--cov=src/spreadsheet_handling \
		--cov-report=html:$(COV_HTML_DIR) \
		tests
	@echo "Open HTML report: file://$(COV_HTML_DIR)/index.html"

# =========================
# Tests
# =========================

.PHONY: test test-verbose test-lastfailed test-one test-file test-node test-unit test-integ test-legacy test-all

# Central knobs (kept as-is)
PYTEST_BASEOPTS   ?= -q
SHEETS_LOG        ?=
LOG_OPTS          ?=

# NEW: default to excluding legacy tests everywhere
# Override MARK_EXPR on the command line to include/exclude categories.
# Examples:
#   make test-all                        # run all tests (clears MARK_EXPR)
#   make test MARK_EXPR=                 # same as above, run all
#   make test MARK_EXPR="not slow"       # exclude @pytest.mark.slow
#   make test MARK_EXPR="integ"          # only integration tests
#   make test-verbose LOG_OPTS="-x"      # fail fast
#   make test-one TESTPATTERN="helpers and not slow"
#   make test-one TESTPATTERN="integration or json_roundtrip or xlsx_writer_styling"
# --- bestehend ---
MARK_EXPR         ?= not legacy
MARK_OPT          := $(if $(MARK_EXPR),-m "$(MARK_EXPR)",)

# NEU: wenn "not legacy" drin steht, den Ordner wirklich ignorieren
IGNORE_OPT        := $(if $(findstring not legacy,$(MARK_EXPR)),--ignore=tests/legacy,)

# Default: run suite (quiet) with legacy excluded by default
test: deps-dev ## Run test suite (quiet, excludes legacy by default)
	$(PYTEST) $(PYTEST_BASEOPTS) $(MARK_OPT) $(IGNORE_OPT) $(LOG_OPTS) tests

test-verbose: deps-dev ## Verbose tests with inline logs
	SHEETS_LOG=INFO $(PYTEST) -vv -s $(MARK_OPT) $(IGNORE_OPT) $(LOG_OPTS) tests

test-lastfailed: deps-dev ## Only last failed tests, verbose & logs
	SHEETS_LOG=DEBUG $(PYTEST) --lf -vv $(MARK_OPT) $(IGNORE_OPT) $(LOG_OPTS) tests

test-one: deps-dev ## Run tests filtered by pattern (set TESTPATTERN=...)
	@if [ -z "$(TESTPATTERN)" ]; then echo "Set TESTPATTERN=..."; exit 2; fi
	SHEETS_LOG=DEBUG $(PYTEST) -vv -k "$(TESTPATTERN)" $(MARK_OPT) $(IGNORE_OPT) $(LOG_OPTS) tests

test-file: deps-dev ## Run a single test file (set FILE=...)
	@if [ -z "$(FILE)" ]; then echo "Set FILE=path/to/test_file.py"; exit 2; fi
	$(PYTEST) -vv $(MARK_OPT) $(IGNORE_OPT) $(LOG_OPTS) $(FILE)

test-node: deps-dev ## Run a single test node (set NODE=file::test)
	@if [ -z "$(NODE)" ]; then echo "Set NODE=file::test_name"; exit 2; fi
	$(PYTEST) -vv $(MARK_OPT) $(IGNORE_OPT) $(LOG_OPTS) $(NODE)

test-unit: deps-dev ## Unit tests only (exclude integration)
	$(PYTEST) $(PYTEST_BASEOPTS) -m "not integ" $(IGNORE_OPT) $(LOG_OPTS) tests

test-integ: deps-dev ## Integration tests only
	$(PYTEST) $(PYTEST_BASEOPTS) -m "integ" $(IGNORE_OPT) $(LOG_OPTS) tests

# Everything (opt-in): clear MARK_EXPR so no filter is applied
test-all: MARK_EXPR=
test-all: deps-dev ## Run ALL tests (including legacy)
	$(PYTEST) $(PYTEST_BASEOPTS) $(LOG_OPTS) tests

# =========================
# Demo run
# =========================
run: deps ## Demo: roundtrip on example
	$(VENV)/bin/sheets-pack \
	  examples/roundtrip_start.json \
	  -o $(TARGET)/demo.xlsx \
	  --levels 3
	$(VENV)/bin/sheets-unpack \
	  $(TARGET)/demo.xlsx \
	  -o $(TARGET)/demo_out \
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
