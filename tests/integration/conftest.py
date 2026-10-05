"""The integration tests' stage: callers, their host directories, and Rocky.

These run as root inside the Rocky image, set up by run.sh. Each test plays a
host user -- a Caller -- running the installed Rocky CLI against the fake
docker, which starts every "container" with the image's real entrypoint.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

import pytest

IT: Final = Path("/opt/rocky-it")
ROCKY: Final = IT / "venv" / "bin" / "rocky"
FAKE_DOCKER: Final = IT / "bin" / "docker"
HOSTS: Final = Path("/tmp/rocky-it")


@dataclass(frozen=True)
class Caller:
    """A host user who runs Rocky."""

    name: str
    uid: int
    gid: int


# macOS puts everyone in staff, gid 20, which Debian ships as dialout.
MAC: Final = Caller("mac", 501, 20)
# The image's own user, so the entrypoint has nothing to renumber.
LINUX: Final = Caller("rocky", 1000, 1000)
ROOT: Final = Caller("root", 0, 0)
# A uid nothing in the image uses.
STRAY: Final = Caller("stray", 4242, 4242)

CALLERS: Final = (MAC, LINUX, ROOT, STRAY)


def image_env() -> dict[str, str]:
    """The environment the image gives every container, as run.sh recorded it."""
    lines = (IT / "image.env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def exists(database: str, number: int) -> bool:
    """Whether getent finds number in database: passwd or group."""
    lookup = ["getent", database, str(number)]
    return subprocess.run(lookup, check=False, capture_output=True).returncode == 0


@pytest.fixture(scope="session", autouse=True)
def callers() -> None:
    """Give every caller an account, then snapshot /etc for the fake docker.

    sudo, which the fake docker CLI uses to reach its "daemon", wants the
    caller to exist. The snapshot is what each container's /etc starts from.
    """
    for caller in CALLERS:
        if not exists("group", caller.gid):
            subprocess.run(["groupadd", "-g", str(caller.gid), caller.name], check=True)
        if not exists("passwd", caller.uid):
            subprocess.run(
                [
                    "useradd",
                    "-M",
                    "-u",
                    str(caller.uid),
                    "-g",
                    str(caller.gid),
                    caller.name,
                ],
                check=True,
            )
    for name in ("passwd", "group", "shadow", "gshadow"):
        shutil.copy2(Path("/etc") / name, IT / "etc" / name)


@dataclass(frozen=True)
class Host:
    """One caller's side of the machine: a project, Rocky's state, and Rocky."""

    caller: Caller
    root: Path

    @property
    def project(self) -> Path:
        return self.root / "project"

    @property
    def state(self) -> Path:
        return self.root / "state"

    def home(self, profile: str = "main") -> Path:
        """A profile's home, as seen from the host."""
        return self.state / "profiles" / profile

    def command(self, *args: str) -> list[str]:
        """The command line that runs `rocky args...` as this caller."""
        environment = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(self.root),
            "ROCKY_DOCKER": str(FAKE_DOCKER),
            "ROCKY_STATE_DIR": str(self.state),
            "ROCKY_IT_IMAGE": os.environ["ROCKY_IT_IMAGE"],
            "ROCKY_IT_DIGEST": os.environ["ROCKY_IT_DIGEST"],
        }
        return [
            "setpriv",
            f"--reuid={self.caller.uid}",
            f"--regid={self.caller.gid}",
            "--clear-groups",
            "env",
            "-i",
            *(f"{name}={value}" for name, value in environment.items()),
            str(ROCKY),
            *args,
        ]

    def rocky(
        self, *args: str, stdin: str = "", timeout: float = 120
    ) -> subprocess.CompletedProcess[str]:
        """Run `rocky args...` as this caller, in its project directory."""
        return subprocess.run(
            self.command(*args),
            cwd=self.project,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def run(self, *command: str, stdin: str = "") -> str:
        """`rocky run command...`, which must succeed; returns its stdout."""
        result = self.rocky("run", *command, stdin=stdin)
        assert result.returncode == 0, result.stderr
        return result.stdout

    def write(self, path: Path, text: str) -> None:
        """Write a file on the host side, owned by the caller."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        own(path, self.caller)


def own(path: Path, caller: Caller) -> None:
    os.chown(path, caller.uid, caller.gid)


def owner(path: Path) -> tuple[int, int]:
    stat = path.lstat()
    return stat.st_uid, stat.st_gid


def make_host(caller: Caller, test_name: str) -> Host:
    """A fresh host directory for caller, which only it may write to."""
    HOSTS.mkdir(mode=0o755, exist_ok=True)
    root = HOSTS / re.sub(r"[^a-zA-Z0-9]+", "-", test_name).strip("-")
    shutil.rmtree(root, ignore_errors=True)
    host = Host(caller, root)
    for directory in (root, host.project, host.state):
        directory.mkdir()
        own(directory, caller)
    return host


class MakeHost(Protocol):
    """The make fixture: call it with a Caller for a Host."""

    def __call__(self, caller: Caller) -> Host: ...


@pytest.fixture
def make(request: pytest.FixtureRequest) -> Iterator[MakeHost]:
    """Makes a Host for any caller; each test gets its own directories."""
    made: list[Host] = []

    def make_one(caller: Caller) -> Host:
        host = make_host(caller, f"{request.node.name}-{caller.name}")
        made.append(host)
        return host

    yield make_one
    for host in made:
        shutil.rmtree(host.root, ignore_errors=True)


@pytest.fixture
def mac(make: MakeHost) -> Host:
    """The usual host: a macOS-shaped caller, whose gid is taken in the image."""
    return make(MAC)
