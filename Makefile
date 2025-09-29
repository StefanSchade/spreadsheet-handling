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
# Tests
# =========================
test: deps-dev ## Run full test suite (quiet)
	$(PYTHON) -m pytest tests -q

test-verbose: setup ## Verbose tests with inline logs
	SHEETS_LOG=INFO $(PYTHON) -m pytest -vv -s $(LOG_OPTS) tests

test-lastfailed: deps-dev ## Only last failed tests, verbose & logs
	SHEETS_LOG=DEBUG $(PYTHON) -m pytest --lf -vv $(LOG_OPTS) tests

# usage: make test-one TESTPATTERN="fk_multi_targets"
test-one: deps-dev ## Run tests filtered by pattern (set TESTPATTERN=...)
	SHEETS_LOG=DEBUG $(PYTHON) -m pytest -vv -k "$(TESTPATTERN)" $(LOG_OPTS) tests

# usage: make test-file FILE=tests/test_fk_helpers_pack.py
test-file: deps-dev ## Run a single test file (set FILE=...)
	$(PYTHON) -m pytest -vv $(LOG_OPTS) $(FILE)

# usage: make test-node NODE='tests/test_fk_helpers_pack.py::test_fk_helper_is_added_in_csv'
test-node: deps-dev ## Run a single test node (set NODE=file::test)
	$(PYTHON) -m pytest -vv $(LOG_OPTS) $(NODE)

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
