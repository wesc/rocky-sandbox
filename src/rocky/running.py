"""The containers Rocky started, read back from docker by their labels."""

from __future__ import annotations

import json
import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from rocky.container import PROFILE_LABEL, WORKDIR_LABEL
from rocky.settings import Settings


class MalformedInspect(ValueError):
    """`docker inspect` printed something Rocky cannot read."""


@dataclass(frozen=True)
class RunningContainer:
    id: str
    name: str
    profile: str
    workdir: Path
    """The host directory the container was started in."""

    started: datetime
    command: tuple[str, ...]


class DockerFailed(Exception):
    def __init__(self, status: int, stderr: str) -> None:
        super().__init__(stderr.strip())
        self.status = status


def containers(settings: Settings) -> list[RunningContainer]:
    """Every running container with Rocky's workdir label. Raises DockerFailed.

    Reads the labels from `docker inspect`'s JSON. `docker ps --format` joins
    labels with commas, and a path can contain one.
    """
    ids = docker_output(
        settings, "ps", "--quiet", "--no-trunc", "--filter", f"label={WORKDIR_LABEL}"
    ).split()
    if not ids:
        return []
    return parse_inspect(docker_output(settings, "inspect", *ids))


def docker_output(settings: Settings, *args: str) -> str:
    docker = subprocess.run(
        [settings.docker, *args], capture_output=True, text=True, check=False
    )
    if docker.returncode != 0:
        raise DockerFailed(docker.returncode, docker.stderr)
    return docker.stdout


def parse_inspect(text: str) -> list[RunningContainer]:
    """The containers in `docker inspect`'s output."""
    try:
        items: object = json.loads(text)
    except json.JSONDecodeError as error:
        raise MalformedInspect(str(error)) from None
    if not isinstance(items, list):
        raise MalformedInspect("expected a JSON array")
    return [parse_container(item) for item in items]


def parse_container(item: object) -> RunningContainer:
    """One element of `docker inspect`'s array."""
    labels = field(item, "Config", "Labels")
    command = field(item, "Config", "Cmd")
    if not isinstance(command, list) or not all(isinstance(c, str) for c in command):
        raise MalformedInspect("Config.Cmd is not a list of strings")
    return RunningContainer(
        id=text_field(item, "Id"),
        name=text_field(item, "Name").removeprefix("/"),
        profile=text_field(labels, PROFILE_LABEL),
        workdir=Path(text_field(labels, WORKDIR_LABEL)),
        started=parse_started(text_field(item, "State", "StartedAt")),
        command=tuple(command),
    )


def field(value: object, *path: str) -> object:
    """value[path[0]][path[1]]..., checking at each step."""
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise MalformedInspect(f"no {'.'.join(path)}")
        value = value[key]
    return value


def text_field(value: object, *path: str) -> str:
    found = field(value, *path)
    if not isinstance(found, str):
        raise MalformedInspect(f"{'.'.join(path)} is not a string")
    return found


def parse_started(stamp: str) -> datetime:
    """Docker's StartedAt, such as 2026-10-05T12:00:00.123456789Z."""
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        raise MalformedInspect(f"State.StartedAt is not a time: {stamp!r}") from None


def format_age(age: timedelta) -> str:
    """The largest whole unit of age: 45s, 12m, 3h or 2d."""
    seconds = max(0, int(age.total_seconds()))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def format_table(found: Sequence[RunningContainer], *, now: datetime) -> str:
    header = ["CONTAINER", "NAME", "PROFILE", "UP", "DIRECTORY", "COMMAND"]
    rows = [header] + [
        [
            container.id[:12],
            container.name,
            container.profile,
            format_age(now - container.started),
            str(container.workdir),
            shlex.join(container.command),
        ]
        for container in found
    ]
    # The last column is not padded, so no line ends in spaces.
    widths = [max(len(row[i]) for row in rows) for i in range(len(header) - 1)]
    return "".join(
        "".join(
            f"{cell.ljust(width)}  "
            for cell, width in zip(row[:-1], widths, strict=True)
        )
        + row[-1]
        + "\n"
        for row in rows
    )
