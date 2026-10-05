"""Profiles, mount paths, hostnames, and the `docker run` argv."""

import csv
import hashlib
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

import pytest

from rocky.container import (
    DEFAULT_PROFILE,
    LOGIN_PORT,
    Caller,
    InvalidProfileName,
    ProfileName,
    RunRequest,
    docker_run_argv,
    hostname,
    profile_name,
    safe_directory_name,
    workspace_path,
)
from rocky.settings import Settings

SETTINGS = Settings(
    image_override=None, state_dir=Path("/state"), docker="/usr/bin/docker"
)
IMAGE = "rocky:0123456789abcdef"


def caller(workdir: str = "/src/proj.one", *, on_terminal: bool = False) -> Caller:
    return Caller(
        workdir=Path(workdir),
        uid=501,
        gid=20,
        on_terminal=on_terminal,
        terminal_variables={},
    )


def request(
    *command: str, profile: str = DEFAULT_PROFILE, login: bool = False
) -> RunRequest:
    return RunRequest(ProfileName(profile), login=login, command=command)


def option_value(argv: Sequence[str], option: str) -> list[str]:
    """Every value given to option, in order."""
    return [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == option]


def mounts(argv: Sequence[str]) -> list[dict[str, str]]:
    """Every --mount, read as docker reads it: one CSV record of key=value."""
    return [
        dict(field.split("=", 1) for field in next(csv.reader([value])))
        for value in option_value(argv, "--mount")
    ]


# ---------------------------------------------------------------- profiles


@pytest.mark.parametrize("name", ["main", "work", "a", "Work-2", "0day"])
def test_valid_profile_names(name: str) -> None:
    assert profile_name(name) == name


@pytest.mark.parametrize("name", ["", "-lead", "../escape", "a/b", "a_b", "a.b", " a"])
def test_invalid_profile_names(name: str) -> None:
    with pytest.raises(InvalidProfileName):
        profile_name(name)


# ----------------------------------------------------- names and mount paths


@pytest.mark.parametrize(
    ("directory", "safe"),
    [
        ("/src/rocky", "rocky"),
        ("/src/proj.one", "proj-one"),
        ("/src/proj two", "proj-two"),
        ("/src/--odd__name--", "odd-name"),
        ("/src/...", ""),
    ],
)
def test_safe_directory_name(directory: str, safe: str) -> None:
    assert safe_directory_name(Path(directory)) == safe


def hash_of(workdir: str) -> str:
    """The 8 hex digits that identify workdir, computed independently of Rocky."""
    return hashlib.sha256(workdir.encode()).hexdigest()[:8]


def test_hostname_names_profile_directory_and_hash() -> None:
    name = hostname(ProfileName("work"), Path("/src/proj two"))
    assert name == f"erid-work-proj-two-{hash_of('/src/proj two')}"


def test_hostname_and_workspace_share_the_hash() -> None:
    workdir = Path("/src/proj.one")
    name = hostname(DEFAULT_PROFILE, workdir)
    assert name[-8:] == workspace_path(workdir).name[-8:]


def test_namesakes_get_their_own_hostnames() -> None:
    one = hostname(DEFAULT_PROFILE, Path("/src/proj.one"))
    other = hostname(DEFAULT_PROFILE, Path("/elsewhere/proj.one"))
    assert one != other


@pytest.mark.parametrize(
    ("profile", "directory"),
    [
        ("main", "/src/" + "x" * 100),
        ("p" * 70, "/src/proj"),
        ("main", "/src/" + "a-" * 40),
    ],
)
def test_hostname_fits_a_dns_label_and_keeps_the_hash(
    profile: str, directory: str
) -> None:
    name = hostname(ProfileName(profile), Path(directory))
    assert len(name) <= 63
    assert name.endswith(f"-{hash_of(directory)}")
    assert "--" not in name


def test_hostname_without_a_usable_directory_name() -> None:
    name = hostname(DEFAULT_PROFILE, Path("/src/..."))
    assert name == f"erid-main-{hash_of('/src/...')}"


def test_workspace_is_named_and_hashed() -> None:
    workdir = Path("/src/proj.one")
    assert workspace_path(workdir) == PurePosixPath(
        f"/workspace-proj-one-{hash_of('/src/proj.one')}"
    )


def test_namesakes_get_their_own_workspaces() -> None:
    """Claude Code keys project state on the path, so a namesake must not share it."""
    one = workspace_path(Path("/src/proj.one"))
    other = workspace_path(Path("/elsewhere/proj.one"))
    assert one != other
    assert one.name.startswith("workspace-proj-one-")
    assert other.name.startswith("workspace-proj-one-")


def test_workspace_without_a_usable_directory_name() -> None:
    assert workspace_path(Path("/src/...")).name.startswith("workspace-")
    assert "--" not in str(workspace_path(Path("/src/...")))


# ---------------------------------------------------------- docker run argv


def test_run_argv_shape() -> None:
    argv = docker_run_argv(SETTINGS, caller(), IMAGE, request("claude"))
    assert argv[:4] == ["/usr/bin/docker", "run", "--rm", "--init"]
    assert argv[-2:] == [IMAGE, "claude"]


def test_run_mounts_workdir_and_profile_home() -> None:
    argv = docker_run_argv(SETTINGS, caller(), IMAGE, request(profile="work"))
    workspace = workspace_path(Path("/src/proj.one"))
    assert mounts(argv) == [
        {"type": "bind", "source": "/src/proj.one", "target": str(workspace)},
        {"type": "bind", "source": "/state/profiles/work", "target": "/home/rocky"},
    ]
    assert option_value(argv, "--workdir") == [str(workspace)]
    assert option_value(argv, "--hostname") == [
        f"erid-work-proj-one-{hash_of('/src/proj.one')}"
    ]


@pytest.mark.parametrize("name", ["12:00", "a,b", 'say "hi"'])
def test_run_mounts_paths_with_separators_in_them(name: str) -> None:
    """docker -v splits on colons; --mount reads CSV, so quoting covers the rest."""
    workdir = Path("/src") / name
    argv = docker_run_argv(SETTINGS, caller(str(workdir)), IMAGE, request())
    assert mounts(argv)[0]["source"] == str(workdir)


def test_run_labels_the_container_with_its_directory_and_profile() -> None:
    argv = docker_run_argv(SETTINGS, caller(), IMAGE, request(profile="work"))
    assert option_value(argv, "--label") == [
        "rocky.workdir=/src/proj.one",
        "rocky.profile=work",
    ]


def test_run_passes_the_callers_ids() -> None:
    argv = docker_run_argv(SETTINGS, caller(), IMAGE, request())
    env = option_value(argv, "--env")
    assert "ROCKY_UID=501" in env
    assert "ROCKY_GID=20" in env


def test_run_is_unnamed_so_any_number_can_run() -> None:
    assert "--name" not in docker_run_argv(SETTINGS, caller(), IMAGE, request())


def test_run_always_connects_stdin() -> None:
    argv = docker_run_argv(SETTINGS, caller(), IMAGE, request("cat"))
    assert "--interactive" in argv
    assert "--tty" not in argv


def test_run_allocates_a_tty_only_on_a_terminal() -> None:
    argv = docker_run_argv(SETTINGS, caller(on_terminal=True), IMAGE, request())
    assert "--tty" in argv


def test_run_passes_terminal_variables() -> None:
    with_term = Caller(
        workdir=Path("/src/p"),
        uid=1,
        gid=1,
        on_terminal=True,
        terminal_variables={"TERM": "xterm-256color"},
    )
    env = option_value(docker_run_argv(SETTINGS, with_term, IMAGE, request()), "--env")
    assert "TERM=xterm-256color" in env


def test_run_publishes_the_login_port_only_on_request() -> None:
    port = f"127.0.0.1:{LOGIN_PORT}:{LOGIN_PORT}"
    plain = docker_run_argv(SETTINGS, caller(), IMAGE, request())
    login = docker_run_argv(SETTINGS, caller(), IMAGE, request(login=True))
    assert option_value(plain, "--publish") == []
    assert option_value(login, "--publish") == [port]


def test_run_passes_the_command_through_untouched() -> None:
    argv = docker_run_argv(SETTINGS, caller(), IMAGE, request("claude", "-p", "--rm"))
    assert argv[-4:] == [IMAGE, "claude", "-p", "--rm"]
