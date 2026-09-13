#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then
  uv sync --frozen --no-dev
  exec uv run --no-sync python -m codester "$@"
fi
python_bin="${CODESTER_PYTHON:-python3}"
"$python_bin" -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ required"'
if [[ ! -x .venv/bin/python ]]; then "$python_bin" -m venv .venv; fi
.venv/bin/python -m pip install -q -e .
exec .venv/bin/python -m codester "$@"
