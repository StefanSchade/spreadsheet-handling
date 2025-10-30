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
TARGET        := $(ROOT)build
DOC_BUILD_DIR := $(TARGET)/doc
VENV          := $(ROOT).venv
COV_HTML_DIR  := $(TARGET)/htmlcov
COV_DATA      := $(TARGET)/.coverage

# System Python executables
SYS_PY       ?= python3
SYS_PIP      ?= pip3

# VENV Python executables
PYTHON       := $(VENV)/bin/python
PYTEST       := ?(VENV)/bin/pytest
RUFF         := $(VENV)/bin/ruff
BLACK        := $(VENV)/bin/black

STAMP_DIR    := $(VENV)/.stamp
DEPS_STAMP   := $(STAMP_DIR)/deps
DEV_STAMP    := $(STAMP_DIR)/dev

PYPROJECT    := $(ROOT)pyproject.toml

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
	@if [ ! -d "$(VENV)" ]; then \
		echo "➡️  Creating virtualenv at $(VENV)"; \
		$(SYS_PY) -m venv "$(VENV)" || { \
			echo ""; \
			echo "❌  Failed to create venv. Ensure 'python3-venv' is installed."; \
			echo "    Ubuntu/WSL: sudo apt install python3-venv"; \
			echo ""; \
			exit 1; \
		}; \
	fi
	@mkdir -p "$(STAMP_DIR)"

.PHONY: ensure-pip
ensure-pip: venv
	@tools/ensure_pip.sh $(PYTHON)

# ==================================
# Project Environment & dependencies
# ==================================
PIP_VERBOSE_FLAG := $(if $(VERBOSE),-v,)

$(DEPS_STAMP): ensure-pip
	@tools/pip_install_spec.sh -p $(PYTHON) -s . $(PIP_VERBOSE_FLAG)
	@mkdir -p "$(STAMP_DIR)"
	@touch "$(DEPS_STAMP)"

$(DEV_STAMP): $(DEPS_STAMP)
	@tools/pip_install_spec.sh -p $(PYTHON) -s '.[dev]' $(PIP_VERBOSE_FLAG)
	@mkdir -p "$(STAMP_DIR)"
	@touch "$(DEV_STAMP)"

deps-dev: venv $(DEV_STAMP) ## Ensure dev deps installed

.PHONY: setup
setup: $(DEV_STAMP)  ## Convenient target to install dev and runtime incl. dependencies

.PHONY: reset-deps
reset-deps: ## Force reinstall deps (deletes stamps) as a workaround for WSL
	@rm -f $(DEPS_STAMP) $(DEV_STAMP)

clean: ## Remove caches and build artifacts
	rm -rf $(TARGET)/
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
DOC_BUILD_DIR ?= build/docs
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

snapshot: ## Repo snapshot under build/
	mkdir -p $(TARGET)
	$(ROOT)tools/repo_snapshot.sh $(ROOT) $(TARGET) $(TARGET)/spreadsheet-handling.txt

# =========================
# Coverage
# =========================
.PHONY: coverage
coverage: deps-dev ## Coverage in terminal (with missing lines)
	mkdir -p $(TARGET)
	COVERAGE_FILE=$(COV_DATA) $(PYTEST) \
		-s $(MARK_OPT) $(IGNORE_OPT) $(LOG_OPTS) \
		--cov=src/spreadsheet_handling \
		--cov-report=term-missing \
		tests

.PHONY: coverage-html
coverage-html: deps-dev ## Coverage as HTML report (build/htmlcov/)
	mkdir -p $(COV_HTML_DIR)
	COVERAGE_FILE=$(COV_DATA) $(PYTEST) \
		-s $(MARK_OPT) $(IGNORE_OPT) $(LOG_OPTS) \
		--cov=src/spreadsheet_handling \
		--cov-report=html:$(COV_HTML_DIR) \
		tests
	@echo "Open HTML report: file://$(COV_HTML_DIR)/index.html"

# =========================
# Test variables (shared)
# =========================

PYTEST 		 := $(shell test -x $(VENV)/bin/pytest && echo $(VENV)/bin/pytest || echo pytest)
PKG_NAME     ?= your_package_name   # <--- anpassen

# Default: Legacy-Tests ausschließen
MARK         ?= not legacy and not xlsx_ir

# Zusätzliche Pytest-Optionen (CLI-Override möglich)
PYTEST_OPTS  ?=

# Testauswahl (Verzeichnis/Datei/Pfad); leer => Standard "tests"
TEST_PATH    ?=

# =========================
# Test targets
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
MARK_EXPR         ?= not legacy and not xlsx_ir
MARK_OPT          := $(if $(MARK_EXPR),-m "$(MARK_EXPR)",)

# NEU: wenn "not legacy" drin steht, den Ordner wirklich ignorieren
IGNORE_OPT        := $(if $(findstring not legacy,$(MARK_EXPR)),--ignore=tests/legacy,)

# Default: run suite (quiet) with legacy excluded by default
test: deps-dev ## Run test suite (quiet, excludes legacy by default)
	$(PYTEST) $(PYTEST_BASEOPTS) $(MARK_OPT) $(IGNORE_OPT) $(LOG_OPTS) tests

# helper used by test-ir / test-legacy (uses venv pytest!)
test-with-marker:
	$(PYTEST) $(PYTEST_BASEOPTS) -m '$(MARK_EXPR)' $(EXTRA_IGNORE) $(LOG_OPTS)

# IR-only: force env + ignore legacy during collection
test-ir:
	SH_XLSX_BACKEND=ir $(MAKE) test-with-marker MARK_EXPR='xlsx_ir' EXTRA_IGNORE='--ignore=tests/legacy'

# Legacy-only: collect only legacy-marked tests (don’t ignore the folder)
test-legacy:
	$(MAKE) test-with-marker MARK_EXPR='legacy' EXTRA_IGNORE=''

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
