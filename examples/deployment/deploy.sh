#!/usr/bin/env bash
# Copy to scripts/deploy.sh in your website repository and edit these four values.
set -euo pipefail
image_repository="my-website"
compose_file="compose.production.yaml"
service="web"
health_url="http://127.0.0.1:8000/health"

# The Dockerfile must include pytest, its dependencies and your tests. The exact
# image tested below is deployed; production secrets/volumes are never passed to pytest.
commit=$(git rev-parse HEAD)
if [[ -n "${CODESTER_DEPLOY_COMMIT:-}" && "$commit" != "$CODESTER_DEPLOY_COMMIT" ]]; then
    echo "Checkout changed since deployment started." >&2
    exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
    echo "Commit or remove checkout changes before deploying." >&2
    exit 1
fi
# Keep tags unique on repeated builds of the same commit, and retain old images.
release="${commit}-$(date +%s)-$$"
export CODESTER_DEPLOY_IMAGE="${image_repository}:${release}"
compose=(docker compose -f "$compose_file")

printf '\n[1/4] Build %s\n' "$CODESTER_DEPLOY_IMAGE"
docker build --label "org.opencontainers.image.revision=$commit" -t "$CODESTER_DEPLOY_IMAGE" .
image_id=$(docker image inspect --format '{{.Id}}' "$CODESTER_DEPLOY_IMAGE")

printf '\n[2/4] Run pytest against %s\n' "$image_id"
docker run --rm --network none --entrypoint python "$image_id" -m pytest -q

# Inspect configuration before changing the running service. The Compose service
# must use CODESTER_DEPLOY_IMAGE, with no source-code bind mount replacing the image.
"${compose[@]}" config --quiet
containers=$("${compose[@]}" ps -q "$service")
if [[ -n "$containers" ]]; then
    if [[ "$containers" == *$'\n'* ]]; then
        echo "This example supports one application container. Adapt it for replicas." >&2
        exit 1
    fi
    previous_image=$(docker inspect --format '{{.Image}}' "$containers")
    docker image tag "$previous_image" "${image_repository}:previous"
    printf 'Previous image retained: %s (%s:previous)\n' "$previous_image" "$image_repository"
fi
# Catch accidental retagging between the test and promotion.
if [[ "$(docker image inspect --format '{{.Id}}' "$CODESTER_DEPLOY_IMAGE")" != "$image_id" ]]; then
    echo "Image changed after testing. Deployment stopped." >&2
    exit 1
fi
printf '\n[3/4] Deploy tested image to production\n'
"${compose[@]}" up --no-build --pull never --no-deps --wait --wait-timeout 120 "$service"

printf '\n[4/4] Check deployed image and website\n'
container=$("${compose[@]}" ps -q "$service")
if [[ -z "$container" || "$(docker inspect --format '{{.Image}}' "$container")" != "$image_id" ]]; then
    echo "The running container does not use the tested image. Inspect production." >&2
    exit 1
fi
curl --fail --silent --show-error --max-time 15 "$health_url" >/dev/null
printf 'Deployment checks passed for commit %s\n' "$commit"
# No image pruning, database migration or automatic rollback is performed here.
