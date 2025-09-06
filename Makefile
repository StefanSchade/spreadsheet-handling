# =========================
# Project variables
# =========================
ROOT         := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
TARGET       := $(ROOT)build
SCRIPTS      := $(ROOT)scripts
PKGDIR       := $(SCRIPTS)/spreadsheet_handling
VENV         := $(ROOT).venv
COV_HTML_DIR := $(TARGET)/htmlcov
COV_DATA     := $(TARGET)/.coverage

PYTHON       := $(VENV)/bin/python
PIP          := $(VENV)/bin/pip
PYTEST       := $(VENV)/bin/pytest
RUFF         := $(VENV)/bin/ruff
BLACK        := $(VENV)/bin/black

STAMP_DIR    := $(VENV)/.stamp
DEPS_STAMP   := $(STAMP_DIR)/deps
DEV_STAMP    := $(STAMP_DIR)/dev

PYPROJECT    := $(PKGDIR)/pyproject.toml  # trigger for reinstalls

# pytest logging options for debug runs
LOG_OPTS  ?= -o log_cli=true -o log_cli_level=DEBUG

# =========================
# Phony targets
# =========================
.PHONY: help setup reset-deps clean venv \
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
$(DEPS_STAMP): $(PYPROJECT) | venv  ## Install runtime deps + package (editable)
	$(PIP) install -e $(PKGDIR)
	@mkdir -p $(STAMP_DIR)
	@touch $(DEPS_STAMP)

deps: $(DEPS_STAMP) ## Ensure runtime deps installed

# Dev tools (ruff/black/pytest/pytest-cov/pyyaml) via extras
$(DEV_STAMP): $(DEPS_STAMP) $(PYPROJECT) ## Install dev tools (extras 'dev')
	$(PIP) install -e $(PKGDIR)[dev]
	@mkdir -p $(STAMP_DIR)
	@touch $(DEV_STAMP)

deps-dev: $(DEV_STAMP) ## Ensure dev deps installed

setup: deps-dev ## One-shot: create venv + install runtime & dev deps

reset-deps: ## Force reinstall deps (deletes stamps)
	@rm -f $(DEPS_STAMP) $(DEV_STAMP)

clean: ## Remove caches and build artifacts
	rm -rf $(PKGDIR)/tmp
	rm -rf $(TARGET)/
	find $(ROOT) -type d -name '__pycache__' -prune -exec rm -rf {} +
	find $(ROOT) -type d -name '.pytest_cache' -prune -exec rm -rf {} +
	find $(PKGDIR) -maxdepth 1 -type d -name '*.egg-info' -prune -exec rm -rf {} +
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
	$(RUFF) check scripts/spreadsheet_handling --fix
	$(BLACK) scripts/spreadsheet_handling

lint: deps-dev ## Lint only (Ruff)
	$(RUFF) check scripts/spreadsheet_handling

syntax: venv ## Syntax check
	$(PYTHON) -m compileall -q scripts/spreadsheet_handling

ci: syntax lint test ## Run syntax + lint + tests

# =========================
# Tests
# =========================
test: deps-dev ## Run full test suite (quiet)
	$(PYTEST) scripts/spreadsheet_handling/tests -q

test-verbose: deps-dev ## Verbose tests with inline logs
	SHEETS_LOG=INFO $(PYTEST) -vv -s $(LOG_OPTS) scripts/spreadsheet_handling/tests

test-lastfailed: deps-dev ## Only last failed tests, verbose & logs
	SHEETS_LOG=DEBUG $(PYTEST) --lf -vv $(LOG_OPTS) scripts/spreadsheet_handling/tests

# usage: make test-one TESTPATTERN="fk_multi_targets"
test-one: deps-dev ## Run tests filtered by pattern (set TESTPATTERN=...)
	SHEETS_LOG=DEBUG $(PYTEST) -vv -k "$(TESTPATTERN)" $(LOG_OPTS) scripts/spreadsheet_handling/tests

# usage: make test-file FILE=scripts/.../test_fk_helpers_pack.py
test-file: deps-dev ## Run a single test file (set FILE=...)
	$(PYTEST) -vv $(LOG_OPTS) $(FILE)

# usage: make test-node NODE='scripts/.../test_fk_helpers_pack.py::test_fk_helper_is_added_in_csv'
test-node: deps-dev ## Run a single test node (set NODE=file::test)
	$(PYTEST) -vv $(LOG_OPTS) $(NODE)

# =========================
# Snapshot
# =========================
snapshot: ## Repo snapshot under build/
	mkdir -p $(TARGET)
	$(ROOT)scripts/repo_snapshot.sh $(ROOT) $(TARGET) $(TARGET)/repo.txt

# =========================
# Coverage
# =========================
coverage: deps-dev ## Coverage in terminal (with missing lines)
	mkdir -p $(TARGET)
	COVERAGE_FILE=$(COV_DATA) $(PYTEST) \
		--cov=scripts/spreadsheet_handling/src/spreadsheet_handling \
		--cov-report=term-missing \
		scripts/spreadsheet_handling/tests

coverage-html: deps-dev ## Coverage as HTML report (build/htmlcov/)
	mkdir -p $(COV_HTML_DIR)
	COVERAGE_FILE=$(COV_DATA) $(PYTEST) \
		--cov=scripts/spreadsheet_handling/src/spreadsheet_handling \
		--cov-report=html:$(COV_HTML_DIR) \
		scripts/spreadsheet_handling/tests
	@echo "Open HTML report: file://$(COV_HTML_DIR)/index.html"

# =========================
# Demo run
# =========================
run: deps ## Demo: roundtrip on example
	$(VENV)/bin/json2sheet \
	  $(PKGDIR)/examples/roundtrip_start.json \
	  -o $(PKGDIR)/tmp/tmp.xlsx \
	  --levels 3
	$(VENV)/bin/sheet2json \
	  $(PKGDIR)/tmp/tmp.xlsx \
	  -o $(PKGDIR)/tmp/tmp.json \
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
