#!/usr/bin/env bash
# Creates .venv and installs dev tooling plus both services in editable mode. Reads and writes no secrets.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]' -e services/release-api -e services/release-mcp

echo "Bootstrap complete. Run: .venv/bin/ruff check . && .venv/bin/mypy . && .venv/bin/pytest -q"
