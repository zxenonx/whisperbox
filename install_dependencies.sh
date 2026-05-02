#!/bin/bash
set -e
cd /app
uv sync --frozen --no-dev --no-install-project --python-preference system
