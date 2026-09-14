#!/bin/sh
set -eu

auth_file="${CODEX_AUTH_FILE:-$HOME/.codex/auth.json}"
if [ ! -f "$auth_file" ]; then
  echo "Codex login cache not found at $auth_file" >&2
  echo "Run 'codex login' on this computer first, then retry." >&2
  exit 1
fi

docker compose up -d codester >/dev/null
docker compose exec -T codester sh -c '
  mkdir -p /data/codex
  chmod 700 /data/codex
  cat > /data/codex/auth.json.tmp
  chmod 600 /data/codex/auth.json.tmp
  mv /data/codex/auth.json.tmp /data/codex/auth.json
' < "$auth_file"

docker compose exec -T codester codex login status
echo "Codex login imported. Enable Codex monitoring in Codester Settings."
