# Rocky

A lightweight sandboxed container for spinning up coding agents in the current directory.

Rocky is a small Python tool. It builds a Debian image with the usual toolchains (Node via nvm,
Rust via rustup, `uv`) plus the coding agents — [Claude Code](https://claude.com/claude-code) and
pi, each with its ACP adapter (`claude-agent-acp`, `pi-acp`) — and then runs disposable containers
over your current directory. This is a method of spinning up a sandboxed coding agent quickly and
without any fuss. For more complex use cases, check out [Development
Containers](https://containers.dev) or [Agent
Circus](https://github.com/Embedded-Focus/agent-circus).

Rocky mounts two useful directories:

- `$PWD` → `/workspace-<name>-<hash>`, so the container sees the project you are working on.
- `~/.rocky/profiles/<profile>` → `/home/rocky`, the home directory of the profile you run under.
  Agent logins live there, so they survive the container and you log in once, not once per project.

## Install

```
uv tool install git+https://github.com/wesc/rocky-sandbox
rocky build
```

Rocky needs Docker and Python 3.12 or later. `uv tool install` downloads a Python if yours is
older.

`uv tool upgrade rocky-sandbox` moves to the latest commit on `main`. To pin a release, install
`git+https://github.com/wesc/rocky-sandbox@v0.1.0`. The package is called `rocky-sandbox` because
`rocky` is taken on PyPI. The command it installs is `rocky`.

## Usage

```
rocky run [options] [command...]   open a shell, or run a command, in $PWD
rocky build                        build the image; needed before the first run
rocky build --update               rebuild with the latest agents and base image
rocky ps                           list Rocky's containers and their directories
rocky image                        print the tag of the image this Rocky runs
rocky print-context DIR            write the Dockerfile and entrypoint to DIR
rocky help                         show the command list
```

Options to `rocky run` go before the command. Everything after the command passes through to it, so
`rocky run -p work claude -p "hi"` runs `claude -p "hi"` under the `work` profile.

```
-p, --profile NAME   run under profile NAME (default: main)
--login              publish the OAuth callback port that `claude` logs in on
--                   end the options, for a command that starts with a dash
```

Every command takes `--help`, for example `rocky run --help`.

`rocky run` never builds the image. When the image is missing, it tells you to run `rocky build`.
Each version of Rocky has its own image, tagged with a digest of its Dockerfile and entrypoint, so
an upgrade may ask you to build again. `docker image ls rocky` lists old images to remove.

`rocky run` also works as a stdio subprocess, so an editor can launch an ACP adapter with `rocky run
pi-acp`.

Every Rocky container has an empty file at `/.rockyenv`. A script or shell prompt can test for it
to tell it runs in Rocky, as `/.dockerenv` tells it runs in Docker.

## Profiles

A profile is one persistent home directory. Everything an agent keeps in its home — OAuth logins,
API tokens, settings, per-project history — belongs to the profile. Separate profiles share the
same Rocky Docker image, but have different home directories.

```
rocky run claude            # the default profile, main
rocky run -p work claude    # a separate home: its own logins and tokens
```

Rocky creates a profile the first time you use it. To delete a profile, delete its directory under
`~/.rocky/profiles`.

## Workspaces and containers

Each host directory gets its own workspace path: `~/src/myproject` mounts at something like
`/workspace-myproject-3f9a01c2`. Coding agents treat each workspace path as a separate project.

Containers run with `--rm`, and you can run any number at once, under the same profile or different
ones. Each container's hostname names its profile, its directory and the same hash as its workspace
path, for example `erid-main-myproject-3f9a01c2`. `rocky ps` lists every running Rocky container
and the directory it started in:

```
$ rocky ps
CONTAINER     NAME           PROFILE  UP   DIRECTORY           COMMAND
9a0d44c1e8f2  eager_hopper   work     2h   /home/me/src/app    pi-acp
3f1c0a9e2b71  quirky_turing  main     12m  /home/me/src/app    claude
51be07d3c6a0  vibrant_noyce  main     3d   /home/me/src/rocky  bash
```

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `ROCKY_IMAGE` | `rocky:<digest>` | a fixed image tag to build and run instead |
| `ROCKY_STATE_DIR` | `~/.rocky` | host directory that holds the profiles, under `profiles/` |
| `ROCKY_DOCKER` | `docker` | container CLI to run |

## Developing Rocky

```
git clone https://github.com/wesc/rocky-sandbox ~/src/rocky-sandbox
cd ~/src/rocky-sandbox
uv sync --locked      # .venv with Rocky and the dev tools, from uv.lock
scripts/check.sh      # lint, types, unit tests
```

Read `AGENTS.md` before you change anything. It holds the rules for code, comments, tests and
commits.

### Dependencies

Rocky's one runtime dependency is click, pinned to an exact version in `pyproject.toml`. `uv.lock`
pins every package, dev tools included, with its SHA-256 hash, and uv checks those hashes when it
installs. The scripts run uv with `--locked`, so they fail if `uv.lock` is out of date. `uv tool
install` does not read `uv.lock`, so the exact versions in `pyproject.toml` are what users get.

### Layout

| Path | Contents |
| --- | --- |
| `src/rocky/cli.py` | the `rocky` command: one click command per subcommand |
| `src/rocky/settings.py` | reads the `ROCKY_*` environment variables |
| `src/rocky/image.py` | the build context, its digest and tag, and `docker build` |
| `src/rocky/container.py` | profiles, mount paths, hostnames, and the `docker run` arguments |
| `src/rocky/running.py` | finds the running containers by label, for `rocky ps` |
| `src/rocky/context/` | the image's `Dockerfile` and `entrypoint.sh` |
| `tests/unit/` | fast tests: no docker, no root, no network |
| `tests/integration/` | end-to-end tests that run inside the Rocky image |
| `scripts/` | `check.sh` and `integration.sh`, which run the two kinds of tests |

What happens inside the container is in `src/rocky/context/`. The Dockerfile's comments explain
where the toolchains live and why any user can write to them. `entrypoint.sh` explains how the
container's user takes your uid and gid, and how a command gets the `PATH` of an interactive shell.

### Running a release and a checkout side by side

Keep the release installed for everyday work, and run your checkout under another name:

```
uv tool install git+https://github.com/wesc/rocky-sandbox      # rocky: the release
alias rocky-dev='uv run --project ~/src/rocky-sandbox rocky'   # rocky-dev: your checkout
```

`rocky-dev` runs your edits without a reinstall. If you change the Dockerfile or entrypoint,
`rocky-dev build` makes a separate image, and `rocky` keeps running the release's.

Both use the same profiles, so `rocky-dev` sees your real logins. Try entrypoint changes on a
throwaway profile: `rocky-dev run -p scratch`.

Edit Rocky inside `rocky run`, as you would any other project. Anything that needs docker runs from
a terminal on the host: `rocky-dev build`, `rocky-dev run`, and `scripts/integration.sh`.

### Testing

`scripts/check.sh` runs ruff, mypy in strict mode, shellcheck, and the unit tests in a few seconds.
It is safe to run anywhere, including inside `rocky run`. Arguments go to pytest, for example
`scripts/check.sh -k profile`.

`scripts/integration.sh` builds the image from your checkout and runs the end-to-end tests inside
it. It needs docker, so it runs only on the host and refuses inside Rocky. The tests run in an
unprivileged container, where a fake docker in `tests/integration/` runs the image's real
entrypoint as several host users. The first run needs the network. The comments in
`tests/integration/` explain how the fake works and what it cannot show.

### Releasing

Bump `version` in `pyproject.toml`, tag the commit to match, and push both:

```
git tag v0.2.0 && git push origin main v0.2.0
```

If a release changes the Dockerfile or entrypoint, its users must run `rocky build`.

## License

Copyright (C) 2026 Wesley Chow <wes.chow@gmail.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.
