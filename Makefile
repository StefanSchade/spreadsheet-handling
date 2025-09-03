.PHONY: run clean venv deps deps-dev test freeze freeze-devi snapshot

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
TARGET := $(ROOT)build
SCRIPTS := $(ROOT)scripts
PKGDIR := $(SCRIPTS)/spreadsheet_handling
VENV := $(ROOT).venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
REQ := $(PKGDIR)/requirements.txt
REQ_DEV := $(PKGDIR)/requirements-dev.txt

run: venv deps
	# console scripts installed into the venv:
	$(VENV)/bin/json2sheet \
	  $(PKGDIR)/examples/roundtrip_start.json \
	  -o $(PKGDIR)/tmp/tmp.xlsx \
	  --levels 3
	$(VENV)/bin/sheet2json \
	  $(PKGDIR)/tmp/tmp.xlsx \
	  -o $(PKGDIR)/tmp/tmp.json \
	  --levels 3

test: venv deps-dev
	$(VENV)/bin/pytest $(PKGDIR)/tests -q

clean:
	rm -rf $(PKGDIR)/tmp
	find $(TARGET) -type d -prune -exec rm -rf {} || true +
	find $(ROOT) -type d -name '__pycache__' -prune -exec rm -rf {} +
	find $(ROOT) -type d -name '.pytest_cache' -prune -exec rm -rf {} +
	find $(ROOT) -name '.~lock.*#' -delete
	find $(PKGDIR) -maxdepth 1 -type d -name '*.egg-info' -prune -exec rm -rf {} +

venv:
	@test -d $(VENV) || python3 -m venv $(VENV)

deps: venv
	$(PIP) install -r $(REQ)
	# install the package itself (editable for dev)
	$(PIP) install -e $(PKGDIR)

deps-dev: venv
	$(PIP) install -r $(REQ_DEV)
	$(PIP) install -e $(PKGDIR)

freeze:
	$(PIP) freeze > $(REQ)

freeze-dev:
	$(PIP) freeze > $(REQ_DEV)

snapshot:
	$(PIP) freeze > $(REQ_DEV)
	mkdir -p $(TARGET)
	$(ROOT)scripts/repo_snapshot.sh $(ROOT) $(TARGET)/repo.txt
