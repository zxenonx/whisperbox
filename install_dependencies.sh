#!/bin/bash
set -e

echo "=== /app contents ==="
ls -la /app/ 2>&1 || echo "(empty or ls failed)"

cd /app

if [ -f uv.lock ] && [ -f pyproject.toml ]; then
    echo "=== found uv.lock + pyproject.toml, running uv sync ==="
    uv sync --frozen --no-dev --no-install-project
elif [ -f requirements.txt ]; then
    echo "=== found requirements.txt, running uv pip install ==="
    uv pip install --system -r requirements.txt
elif [ -f pyproject.toml ]; then
    echo "=== found pyproject.toml only, running uv sync without --frozen ==="
    uv sync --no-dev --no-install-project
else
    echo "ERROR: no recognised dependency file in /app/"
    exit 1
fi
