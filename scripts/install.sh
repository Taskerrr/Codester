#!/usr/bin/env bash
# Install dependencies once, then register native startup for this user.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Darwin ]]; then
  printf 'Automatic startup currently supports macOS and Windows. Use scripts/start.sh on Linux.\n' >&2
  exit 1
fi
# Keep the login service outside Documents/Desktop (macOS protected folders).
source_root="$PWD"
runtime_root="$HOME/Library/Application Support/Codester"
service_target="gui/$(id -u)/local.codester.dashboard"
if launchctl print "$service_target" >/dev/null 2>&1; then
  launchctl bootout "$service_target"
fi
mkdir -p "$runtime_root"
cp pyproject.toml uv.lock "$runtime_root/"
mkdir -p "$runtime_root/codester"
cp -R codester/. "$runtime_root/codester/"
cd "$runtime_root"
if command -v uv >/dev/null 2>&1; then
  uv sync --frozen --no-dev
else
  python_bin="${CODESTER_PYTHON:-python3}"
  "$python_bin" -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ required"'
  if [[ ! -x .venv/bin/python ]]; then "$python_bin" -m venv .venv; fi
  .venv/bin/python -m pip install -e .
fi
# Migration discovers Compose from the original checkout.
export CODESTER_SOURCE_ROOT="$source_root"
exec .venv/bin/python -m codester.native install "$@"
