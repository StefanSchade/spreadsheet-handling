#!/usr/bin/env bash
# pip_install_spec.sh
# Generic pip installer for runtime or dev dependencies.
#
# Examples:
#   tools/pip_install_spec.sh -p .venv/bin/python -s .             # normal install
#   tools/pip_install_spec.sh -p .venv/bin/python -s '.[dev]' -E   # editable install
#   tools/pip_install_spec.sh -p .venv/bin/python -s "-r requirements.txt"
#
# Flags:
#   -p PATH   path to python inside venv (default: .venv/bin/python)
#   -s SPEC   pip install specification (default: '.[dev]')
#   -E        editable install (-e flag)
#   -v        verbose (show pip output)
#   -h        help

set -euo pipefail

VENV_PY=".venv/bin/python"
SPEC=".[dev]"
VERBOSE=0
EDITABLE=0

usage() {
  cat <<EOF
Usage: $0 [-p VENV_PY] [-s SPEC] [-E] [-v]
  -p PATH   path to python inside venv (default: .venv/bin/python)
  -s SPEC   pip install spec, e.g. '.[dev]', '.', '-r requirements.txt'
  -E        editable install (adds -e)
  -v        verbose (show pip output)
  -h        help
EOF
}

while getopts ":p:s:Evh" opt; do
  case "$opt" in
    p) VENV_PY="$OPTARG" ;;
    s) SPEC="$OPTARG" ;;
    E) EDITABLE=1 ;;
    v) VERBOSE=1 ;;
    h) usage; exit 0 ;;
    \?) echo "Unknown option: -$OPTARG" >&2; usage; exit 2 ;;
    :)  echo "Option -$OPTARG requires an argument." >&2; usage; exit 2 ;;
  esac
done

INSTALL_MODE=""
if [ "$EDITABLE" -eq 1 ]; then
  INSTALL_MODE="-e"
fi

echo "➡️  Installing with ${VENV_PY}: pip install ${INSTALL_MODE} ${SPEC}"

if [ ! -x "$VENV_PY" ]; then
  echo "❌  Python executable not found at: $VENV_PY"
  echo "    Run 'make setup' to create the virtualenv first."
  exit 1
fi

# Quiet upgrade of toolchain
"$VENV_PY" -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true

# Compose pip command
PIP_CMD=("$VENV_PY" -m pip install $INSTALL_MODE ${SPEC})

if [ "$VERBOSE" -eq 1 ]; then
  echo "Executing: ${PIP_CMD[*]}"
  if ! "${PIP_CMD[@]}"; then
    echo ""
    echo "❌  pip install ${INSTALL_MODE} ${SPEC} failed."
    echo "    Try manually with:"
    echo "      ${VENV_PY} -m pip install --upgrade pip setuptools wheel"
    echo "      ${VENV_PY} -m pip install ${INSTALL_MODE} '${SPEC}'"
    exit 1
  fi
else
  if ! "${PIP_CMD[@]}" >/dev/null 2>&1; then
    echo ""
    echo "❌  pip install ${INSTALL_MODE} ${SPEC} failed."
    echo "    Re-run with -v for verbose output."
    echo "      $0 -p ${VENV_PY} -s '${SPEC}' ${INSTALL_MODE:+-E} -v"
    exit 1
  fi
fi

echo "✅  Successfully installed: ${INSTALL_MODE:+-e }${SPEC}"
