#! /bin/bash
#

 .venv/bin/python - <<'PY'
from spreadsheet_handling.io_backends.router import LOADERS, SAVERS
print("LOADERS:", sorted(LOADERS.keys()))
print("SAVERS:", sorted(SAVERS.keys()))
PY
LOADERS: ['json', 'json_dir', 'yaml', 'yaml_dir']
SAVERS: ['json', 'json_dir', 'yaml', 'yaml_dir']
