.PHONY: run clean venv deps freeze

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
SCRIPTS := $(ROOT)scripts
VENV := $(ROOT).venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

run: venv deps
	$(SCRIPTS)/start_conversion.sh

clean:
	rm -rf $(SCRIPTS)/spreadsheet_handling/tmp
	# remove all __pycache__ recursively
	find $(ROOT) -type d -name '__pycache__' -prune -exec rm -rf {} +
	# optional Office/Editor locks
	find $(ROOT) -name '.~lock.*#' -delete

venv:
	@test -d $(VENV) || python3 -m venv $(VENV)

deps: venv
	$(PIP) install -r $(ROOT)requirements.txt

freeze:
	$(PIP) freeze > $(ROOT)requirements.txt

