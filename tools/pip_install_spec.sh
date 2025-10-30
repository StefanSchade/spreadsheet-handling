#!/usr/bin/env bash
# pip_install_spec.sh
# Generic installer for a pip install specification.
# Examples:
#   tools/pip_install_spec.sh -p .venv/bin/python -s '.[dev]'
#   tools/pip_install_spec.sh -p .venv/bin/python -s .
#   tools/pip_install_spec.sh -p .venv/bin/python -s "-r requirements.txt"
#
# Flags:
#   -p PATH   path to python inside venv (default: .venv/bin/python)
#   -s SPEC   pip install specification (default: '.[dev]')
#   -v        verbose (show pip output)
#   -h        help

set -euo pipefail

VENV_PY=".venv/bin/python"
SPEC=".[dev]"
VERBOSE=0

usage() {
  cat <<EOF
Usage: $0 [-p VENV_PY] [-s SPEC] [-v]
  -p PATH   path to python inside venv (default: .venv/bin/python)
  -s SPEC   pip install spec, e.g. '.[dev]', '.', '-r requirements.txt'
  -v        verbose (show pip output)
  -h        help
EOF
}

while getopts ":p:s:vh" opt; do
  case "$opt" in
    p) VENV_PY="$OPTARG" ;;
    s) SPEC="$OPTARG" ;;
    v) VERBOSE=1 ;;
    h) usage; exit 0 ;;
    \?) echo "Unknown option: -$OPTARG" >&2; usage; exit 2 ;;
    :)  echo "Option -$OPTARG requires an argument." >&2; usage; exit 2 ;;
  esac
done

echo "➡️  Installing with ${VENV_PY}: pip install -e ${SPEC}"

if [ ! -x "$VENV_PY" ]; then
  echo "❌  Python executable not found at: $VENV_PY"
  echo "    Run 'make setup' to create the virtualenv first."
  exit 1
fi

# Quietly modernize baseline tools; ignore failures (works offline if already present).
"$VENV_PY" -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true

if [ "$VERBOSE" -eq 1 ]; then
  if ! "$VENV_PY" -m pip install -e ${SPEC}; then
    echo ""
    echo "❌  pip install -e ${SPEC} failed."
    echo "    Try:"
    echo "      ${VENV_PY} -m pip install --upgrade pip setuptools wheel"
    echo "      ${VENV_PY} -m pip install -e '${SPEC}'"
    exit 1
  fi
else
  if ! "$VENV_PY" -m pip install -e ${SPEC} >/dev/null 2>&1; then
    echo ""
    echo "❌  pip install -e ${SPEC} failed."
    echo "    Re-run with -v for verbose output, e.g.:"
    echo "      $0 -p ${VENV_PY} -s '${SPEC}' -v"
    exit 1
  fi
fi

echo "✅  Successfully installed: -e ${SPEC}"
