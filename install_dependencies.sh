#!/bin/bash
set -e

echo "=== /app contents ==="
ls -la /app/ 2>&1 || echo "(ls failed)"

echo "=== uv version ==="
uv --version 2>&1

echo "=== python availability ==="
command -v python3 2>&1 || echo "python3 not in PATH"
ls /usr/bin/python* 2>&1 || echo "no python in /usr/bin"

echo "=== UV_PYTHON_CACHE_DIR ==="
echo "${UV_PYTHON_CACHE_DIR:-unset}"

echo "=== uv python list ==="
uv python list 2>&1 || echo "(uv python list failed)"

echo "=== running uv sync ==="
cd /app
uv sync --frozen --no-dev --no-install-project --verbose 2>&1
