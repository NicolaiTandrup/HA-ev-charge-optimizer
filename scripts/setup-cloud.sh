#!/usr/bin/env bash
# Cloud machine setup; application deployments use HA's own Python environment.
set -euo pipefail
export UV_CACHE_DIR=/workspace/.cache/uv
export UV_PYTHON_INSTALL_DIR=/workspace/.local/python
uv python install --no-bin 3.14.8
if [ ! -x /workspace/ev-venv/bin/python ]; then
  uv venv --python 3.14.8 /workspace/ev-venv
fi
cd /workspace/HA-ev-charge-optimizer
uv pip sync --python /workspace/ev-venv/bin/python --require-hashes requirements-dev.lock
/workspace/ev-venv/bin/python --version
/workspace/ev-venv/bin/ruff check custom_components tests
/workspace/ev-venv/bin/ruff format --check custom_components tests
/workspace/ev-venv/bin/python -m pytest
