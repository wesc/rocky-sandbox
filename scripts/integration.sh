#!/usr/bin/env bash
# Builds the image from this checkout and runs the integration tests inside
# it, in an unprivileged container. Needs docker on the host. Arguments go to
# pytest, for example `-k acp`.
set -euo pipefail

if [[ -e /.rockyenv ]]; then
    echo "scripts/integration.sh needs docker, so run it on the host, not in Rocky" >&2
    exit 2
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."
docker="${ROCKY_DOCKER:-docker}"

# The Rocky in the test container looks for the digest tag, not a pinned one.
unset ROCKY_IMAGE

uv run --locked rocky build
image="$(uv run --locked rocky image)"
digest="$("$docker" image inspect -f '{{index .Config.Labels "rocky.context"}}' "$image")"

tty=()
if [[ -t 0 && -t 1 ]]; then
    tty=(--tty)
fi

# The image's own entrypoint would drop root, which the fake daemon needs.
exec "$docker" run --rm --interactive "${tty[@]}" \
    --mount "type=bind,\"source=$PWD\",target=/src,readonly" \
    --env "ROCKY_IT_IMAGE=$image" \
    --env "ROCKY_IT_DIGEST=$digest" \
    --entrypoint /src/tests/integration/run.sh \
    "$image" "$@"
