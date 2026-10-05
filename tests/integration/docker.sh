#!/usr/bin/env bash
# The fake docker CLI, run as the caller. The test container has no docker
# daemon. This answers `image inspect`, and hands `run` to container.sh as root
# through sudo, as the real CLI hands it to a root daemon.
set -euo pipefail

case "${1:-}" in
    image)
        # The only image is the one the tests run in. scripts/integration.sh
        # passes in its tag and context digest.
        if [[ "${2:-}" != inspect || "${*: -1}" != "$ROCKY_IT_IMAGE" ]]; then
            exit 1
        fi
        echo "$ROCKY_IT_DIGEST"
        ;;
    run)
        shift
        exec sudo -n /opt/rocky-it/bin/container "$@"
        ;;
    *)
        echo "fake docker: unsupported: $*" >&2
        exit 125
        ;;
esac
