#!/usr/bin/env bash
# Lint, types, and unit tests. Safe anywhere, including inside `rocky run`.
# Arguments go to pytest.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest "$@"

uv run --locked shellcheck scripts/* src/rocky/context/entrypoint.sh \
    tests/integration/docker.sh tests/integration/container.sh tests/integration/run.sh
