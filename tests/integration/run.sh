#!/usr/bin/env bash
# The test container's entrypoint, started by scripts/integration.sh. Runs as
# root, sets up the fake docker, and runs pytest with these arguments. It takes
# over /home/rocky and /etc/passwd, so it runs only in a disposable container.
set -euo pipefail

IT=/opt/rocky-it

if [[ -z "${ROCKY_IT_IMAGE:-}" || -z "${ROCKY_IT_DIGEST:-}" ]]; then
    echo "run the integration tests with scripts/integration.sh" >&2
    exit 2
fi
if [[ $EUID -ne 0 ]]; then
    echo "the integration tests run as root, to play the docker daemon" >&2
    exit 2
fi
# On a host, /etc/passwd and /home/rocky are the machine's own. Docker creates
# /.dockerenv in every container and Podman creates /run/.containerenv; a host
# has neither.
if [[ ! -e /.dockerenv && ! -e /run/.containerenv ]]; then
    echo "refusing to run: this is not a container" >&2
    exit 2
fi
# Inside `rocky run`, a container too, /home/rocky is a profile's home, with
# every agent's credentials.
if mountpoint -q /home/rocky; then
    echo "refusing to run: /home/rocky is a mount (a rocky profile's home?)" >&2
    exit 2
fi

mkdir -p "$IT/bin" "$IT/etc"

# The image's environment, before this script changes it. The fake docker
# starts each container with it.
env | grep -v -E '^(HOSTNAME|PWD|OLDPWD|SHLVL|_|ROCKY_IT_[A-Z_]+)=' \
    > "$IT/image.env"

# /src is read-only. Work on a copy, without the host's .venv.
mkdir -p "$IT/src"
tar -C /src --exclude=./.venv --exclude=./.git --exclude=./dist -cf - . \
    | tar -C "$IT/src" -xf -

install -m 0755 "$IT/src/tests/integration/docker.sh" "$IT/bin/docker"
install -m 0755 "$IT/src/tests/integration/container.sh" "$IT/bin/container"
echo "ALL ALL=(root) NOPASSWD: $IT/bin/container" > /etc/sudoers.d/rocky-it
chmod 0440 /etc/sudoers.d/rocky-it

# The fake docker moves each profile's home here.
rm -rf /home/rocky

# Installed as a built package, so the build context must arrive as package
# data. Outside /root, because the tests run Rocky as several uids.
export UV_PYTHON_INSTALL_DIR="$IT/python"
export UV_PROJECT_ENVIRONMENT="$IT/venv"
export UV_CACHE_DIR="$IT/cache"
uv sync --quiet --locked --no-editable --project "$IT/src"

cd "$IT/src"
exec "$IT/venv/bin/pytest" -p no:cacheprovider tests/integration "$@"
