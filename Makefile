.PHONY: help run clean venv deps deps-dev test freeze freeze-dev snapshot format lint syntax ci

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
TARGET := $(ROOT)build
SCRIPTS := $(ROOT)scripts
PKGDIR := $(SCRIPTS)/spreadsheet_handling
VENV := $(ROOT).venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff
BLACK := $(VENV)/bin/black
REQ := $(PKGDIR)/requirements.txt
REQ_DEV := $(PKGDIR)/requirements-dev.txt

help:
	@echo "Targets:"
	@echo "  make venv     - create .venv"
	@echo "  make deps     - install runtime deps + package (editable)"
	@echo "  make deps-dev - install dev tools (pytest, ruff, black, autopep8, pyyaml)"
	@echo "  make test     - run tests via venv pytest"
	@echo "  make format   - ruff --fix + black"
	@echo "  make lint     - ruff check"
	@echo "  make syntax   - compileall syntax check"
	@echo "  make ci       - syntax + lint + test"

run: venv deps
	$(VENV)/bin/json2sheet \
	  $(PKGDIR)/examples/roundtrip_start.json \
	  -o $(PKGDIR)/tmp/tmp.xlsx \
	  --levels 3
	$(VENV)/bin/sheet2json \
	  $(PKGDIR)/tmp/tmp.xlsx \
	  -o $(PKGDIR)/tmp/tmp.json \
	  --levels 3

test: venv deps-dev
	$(PYTEST) scripts/spreadsheet_handling/tests -q

clean:
	rm -rf $(PKGDIR)/tmp
	find $(TARGET) -type d -prune -exec rm -rf {} + || true
	find $(ROOT) -type d -name '__pycache__' -prune -exec rm -rf {} +
	find $(ROOT) -type d -name '.pytest_cache' -prune -exec rm -rf {} +
	find $(ROOT) -name '.~lock.*#' -delete
	find $(PKGDIR) -maxdepth 1 -type d -name '*.egg-info' -prune -exec rm -rf {} +

venv:
	@test -d $(VENV) || python3 -m venv $(VENV)

deps: venv
	# Runtime-Install (editable) – Abhängigkeiten kommen aus pyproject.toml
	$(PIP) install -e $(PKGDIR)

deps-dev: deps
	# Dev-Tools minimal & explizit
	$(PIP) install pytest ruff black autopep8 pyyaml

freeze:
	$(PIP) freeze > $(REQ)

freeze-dev:
	$(PIP) freeze > $(REQ_DEV)

snapshot:
	$(PIP) freeze > $(REQ_DEV)
	mkdir -p $(TARGET)
	$(ROOT)scripts/repo_snapshot.sh $(ROOT) $(TARGET) $(TARGET)/repo.txt

format:
	$(RUFF) check scripts/spreadsheet_handling --fix
	$(BLACK) scripts/spreadsheet_handling

lint:
	$(RUFF) check scripts/spreadsheet_handling

syntax:
	$(PYTHON) -m compileall -q scripts/spreadsheet_handling

ci: syntax lint test
