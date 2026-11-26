#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then PY=python; fi
echo "[admet-screening] portable bootstrap (Unix)"
echo "[admet-screening] log directory: logs/"
"$PY" bootstrap.py "$@"
