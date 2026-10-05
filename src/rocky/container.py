"""A container over the caller's directory: its name, its mounts, its `docker run`.

Everything here is pure except Caller.current, which reads the process.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, NewType

from rocky.settings import Settings

ProfileName = NewType("ProfileName", str)
"""A name that matches PROFILE_NAME."""

# A profile name becomes a host directory and part of a hostname.
PROFILE_NAME: Final = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9-]*")
DEFAULT_PROFILE: Final = ProfileName("main")

CONTAINER_HOME: Final = PurePosixPath("/home/rocky")

# Claude Code's OAuth callback port on localhost. Published only with --login:
# a second container that publishes it fails to start.
LOGIN_PORT: Final = 54545

# A prompt that shows the hostname names the sandbox, not the tool, so the
# hostname does not start with `rocky`.
HOSTNAME_PREFIX: Final = "erid"
DNS_LABEL_MAX: Final = 63
WORKSPACE_NAME_MAX: Final = 40

# docker names containers at random. `rocky ps` finds Rocky's by these.
WORKDIR_LABEL: Final = "rocky.workdir"
PROFILE_LABEL: Final = "rocky.profile"

TERMINAL_VARIABLES: Final = ("TERM", "COLORTERM")


class InvalidProfileName(ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(
            f"invalid profile name {name!r}: use letters, digits and "
            "dashes, starting with a letter or digit"
        )


def profile_name(name: str) -> ProfileName:
    if not PROFILE_NAME.fullmatch(name):
        raise InvalidProfileName(name)
    return ProfileName(name)


@dataclass(frozen=True)
class RunRequest:
    """What `rocky run` was asked to do."""

    profile: ProfileName
    login: bool
    command: tuple[str, ...]
    """Empty for the image's default command, a shell."""


@dataclass(frozen=True)
class Caller:
    """Who ran Rocky, from which directory, on what kind of terminal."""

    workdir: Path
    uid: int
    gid: int
    on_terminal: bool
    """Whether stdin and stdout are both terminals."""
    terminal_variables: Mapping[str, str]

    @classmethod
    def current(cls) -> Caller:
        return cls(
            workdir=Path.cwd().resolve(),
            uid=os.getuid(),
            gid=os.getgid(),
            on_terminal=sys.stdin.isatty() and sys.stdout.isatty(),
            terminal_variables={
                name: os.environ[name]
                for name in TERMINAL_VARIABLES
                if os.environ.get(name)
            },
        )


def safe_directory_name(workdir: Path) -> str:
    """workdir's name, with each run of characters outside [a-zA-Z0-9] as one dash."""
    return re.sub(r"[^a-zA-Z0-9]+", "-", workdir.name).strip("-")


def workdir_hash(workdir: Path) -> str:
    """8 hex digits that tell apart two directories with the same name."""
    return hashlib.sha256(str(workdir).encode()).hexdigest()[:8]


def hostname(profile: ProfileName, workdir: Path) -> str:
    """erid-<profile>-<directory>-<hash>, cut to a DNS label. The hash stays whole."""
    suffix = f"-{workdir_hash(workdir)}"
    words = [HOSTNAME_PREFIX, profile, safe_directory_name(workdir)]
    name = "-".join(filter(None, words))
    return name[: DNS_LABEL_MAX - len(suffix)].rstrip("-") + suffix


def workspace_path(workdir: Path) -> PurePosixPath:
    """/workspace-<directory>-<hash>: unique to workdir, and named after it.

    Claude Code keys each project's state on its working directory. One fixed
    path for every project would merge their histories in the profile's home.
    """
    name = safe_directory_name(workdir)[:WORKSPACE_NAME_MAX].rstrip("-")
    words = ["workspace", name, workdir_hash(workdir)]
    return PurePosixPath("/") / "-".join(filter(None, words))


def profile_home(settings: Settings, profile: ProfileName) -> Path:
    return settings.profiles_dir / profile


def bind_mount(source: Path, target: PurePosixPath) -> str:
    """A --mount value. docker reads it as one CSV record, so quoting lets a path
    hold commas and quotes. --volume cannot take a path with a colon."""
    fields = ["type=bind", f"source={source}", f"target={target}"]
    record = io.StringIO()
    csv.writer(record, lineterminator="").writerow(fields)
    return record.getvalue()


def docker_run_argv(
    settings: Settings, caller: Caller, image: str, request: RunRequest
) -> list[str]:
    workspace = workspace_path(caller.workdir)
    argv = [settings.docker, "run", "--rm", "--init"]
    argv += ["--hostname", hostname(request.profile, caller.workdir)]
    argv += ["--workdir", str(workspace)]
    argv += ["--label", f"{WORKDIR_LABEL}={caller.workdir}"]
    argv += ["--label", f"{PROFILE_LABEL}={request.profile}"]
    argv += ["--mount", bind_mount(caller.workdir, workspace)]
    argv += [
        "--mount",
        bind_mount(profile_home(settings, request.profile), CONTAINER_HOME),
    ]
    # The entrypoint gives the container's user these ids.
    argv += ["--env", f"ROCKY_UID={caller.uid}"]
    argv += ["--env", f"ROCKY_GID={caller.gid}"]
    # Without --interactive, docker gives the command /dev/null as stdin.
    argv += ["--interactive"]
    if caller.on_terminal:
        argv += ["--tty"]
    for name, value in caller.terminal_variables.items():
        argv += ["--env", f"{name}={value}"]
    if request.login:
        argv += ["--publish", f"127.0.0.1:{LOGIN_PORT}:{LOGIN_PORT}"]
    return [*argv, image, *request.command]
