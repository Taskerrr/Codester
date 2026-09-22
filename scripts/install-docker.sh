#!/usr/bin/env bash
# Install/update Codester and its user-level Codex integration. Docker bundles Python.
set -euo pipefail
cd "$(dirname "$0")/.."
docker_bin=$(command -v docker)
codex_home="${CODEX_HOST_HOME:-${CODEX_HOME:-$HOME/.codex}}"
export CODEX_HOST_HOME="$codex_home"
mkdir -p "$codex_home"
docker compose up -d --build codester
container_id=$(docker compose ps -q codester)
container_name=$(docker inspect --format '{{.Name}}' "$container_id")
container_name=${container_name#/}
hooks_path="$codex_home/hooks.json"
staged_hooks=$(mktemp "$codex_home/.codester-hooks.XXXXXX")
trap 'rm -f "$staged_hooks"' EXIT
if [[ -f "$hooks_path" ]]; then
  cat "$hooks_path"
else
  printf '{}\n'
fi | docker exec -i "$container_name" python -m codester.codex_hook --configure \
  --docker-bin "$docker_bin" --container "$container_name" > "$staged_hooks"
if [[ ! -f "$hooks_path" ]] || ! cmp -s "$hooks_path" "$staged_hooks"; then
  if [[ -f "$hooks_path" && ! -f "$hooks_path.before-codester" ]]; then
    cp -p "$hooks_path" "$hooks_path.before-codester"
  fi
  mv "$staged_hooks" "$hooks_path"
fi
docker exec "$container_name" python -m codester.codex_hook --enable-activity
printf '\nCodester is running at http://127.0.0.1:8765\n'
printf 'Next: review and trust the Codester hooks in Codex, then start a new turn.\n'
printf 'In the Codex CLI, open /hooks. Existing account login is unchanged.\n'
