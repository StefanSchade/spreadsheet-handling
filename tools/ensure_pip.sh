#!/usr/bin/env bash
set -euo pipefail

# ensure_pip.sh
# Usage: ./tools/ensure_pip.sh /path/to/venv/python

VENV_PY=${1:-.venv/bin/python}

echo "➡️  Ensuring pip using $VENV_PY"

# Try ensurepip first
if ! "$VENV_PY" -m ensurepip --upgrade >/dev/null 2>&1; then
  echo "⚠️  ensurepip failed or not available"
fi

if ! "$VENV_PY" -m pip -V >/dev/null 2>&1; then
  echo "⚠️  pip missing after ensurepip - running get-pip.py"
  TMP_FILE="$(mktemp /tmp/getpip.XXXXXX.py)"
  echo "➡️  Downloading get-pip.py to $TMP_FILE"
  if ! curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$TMP_FILE"; then
    echo "❌  could not download get-pip.py (network/proxy issue)"
    exit 1
  fi

  chmod 644 "$TMP_FILE"
  echo "➡️  Running $VENV_PY $TMP_FILE"
  if ! "$VENV_PY" "$TMP_FILE"; then
    echo "❌  running get-pip.py failed"
    exit 1
  fi
  rm -f "$TMP_FILE"
else
  echo "✅  pip already present"
fi

echo "➡️  Upgrading pip, setuptools, wheel..."
"$VENV_PY" -m pip install --upgrade pip setuptools wheel >/dev/null
echo "✅  pip ready in venv"

