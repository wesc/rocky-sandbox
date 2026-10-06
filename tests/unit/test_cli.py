"""The `rocky` command as a whole, run against a stub `docker`.

The stub records each invocation's argv as JSON and answers `image inspect` as
if the image were built from STUB_IMAGE_DIGEST, or not built at all. It answers
`ps` and `inspect` with the containers in STUB_CONTAINERS, a JSON file in the
shape `docker inspect` prints.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from samples import inspected

from rocky import image
from rocky.container import workspace_path

STUB = """\
#!{python}
import json, os, sys
args = sys.argv[1:]
if args[:2] == ["image", "inspect"]:
    digest = os.environ.get("STUB_IMAGE_DIGEST")
    if digest is None:
        sys.exit(1)
    print(digest)
    sys.exit(0)
if args[:1] in (["ps"], ["inspect"]):
    with open(os.environ["STUB_CONTAINERS"]) as f:
        containers = json.load(f)
    if args[0] == "ps":
        print("".join(c["Id"] + "\\n" for c in containers), end="")
    else:
        print(json.dumps([c for c in containers if c["Id"] in args[1:]]))
    sys.exit(0)
with open(os.environ["STUB_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
"""


@dataclass(frozen=True)
class Result:
    status: int
    stdout: str
    stderr: str
    calls: list[list[str]]
    """Every docker invocation other than `image inspect`, in order."""


@dataclass(frozen=True)
class Rocky:
    """Runs Rocky with a stub docker and a scratch state directory."""

    tmp: Path

    @property
    def state(self) -> Path:
        return self.tmp / "state"

    def __call__(
        self,
        *args: str,
        cwd: Path | None = None,
        digest: str | None = "current",
        docker: str | None = None,
        containers: list[dict[str, object]] | None = None,
    ) -> Result:
        log = self.tmp / "calls.jsonl"
        log.unlink(missing_ok=True)
        env = {
            **os.environ,
            "ROCKY_DOCKER": docker or str(self.tmp / "docker"),
            "ROCKY_STATE_DIR": str(self.state),
            "STUB_LOG": str(log),
            "STUB_CONTAINERS": str(self.tmp / "containers.json"),
        }
        (self.tmp / "containers.json").write_text(json.dumps(containers or []))
        env.pop("ROCKY_IMAGE", None)
        env.pop("STUB_IMAGE_DIGEST", None)
        if digest is not None:
            current = image.context_digest()
            env["STUB_IMAGE_DIGEST"] = current if digest == "current" else digest
        done = subprocess.run(
            [sys.executable, "-m", "rocky", *args],
            cwd=cwd or self.tmp,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        calls = (
            [json.loads(line) for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )
        return Result(done.returncode, done.stdout, done.stderr, calls)


@pytest.fixture
def rocky(tmp_path: Path) -> Rocky:
    stub = tmp_path / "docker"
    stub.write_text(STUB.format(python=sys.executable))
    stub.chmod(0o755)
    return Rocky(tmp_path)


def test_bare_rocky_shows_usage(rocky: Rocky) -> None:
    result = rocky()
    assert result.status == 0
    assert result.calls == []


def test_a_bad_command_line_exits_2_with_usage(rocky: Rocky) -> None:
    result = rocky("bogus")
    assert result.status == 2
    assert "Usage:" in result.stderr
    assert result.calls == []


def test_build_tags_and_labels_by_digest(rocky: Rocky) -> None:
    digest = image.context_digest()
    [call] = rocky("build").calls
    assert call[0] == "build"
    assert ["--label", f"rocky.context={digest}"] == call[1:3]
    assert ["--tag", f"rocky:{digest}"] == call[3:5]
    assert "--pull" not in call


def test_build_update_pulls_and_refreshes_the_agents(rocky: Rocky) -> None:
    [call] = rocky("build", "--update").calls
    assert "--pull" in call
    assert any(arg.startswith("AGENTS_REFRESH=") for arg in call)


def test_an_unbuilt_image_is_never_built_implicitly(rocky: Rocky) -> None:
    result = rocky("run", digest=None)
    assert result.status == 1
    assert "rocky build" in result.stderr
    assert result.calls == []


def test_run_execs_docker_over_the_working_directory(rocky: Rocky) -> None:
    project = rocky.tmp / "proj.one"
    project.mkdir()
    [call] = rocky("run", "claude", cwd=project).calls
    assert call[0] == "run"
    mount = f"type=bind,source={project},target={workspace_path(project)}"
    assert mount in call
    assert call[-2:] == [f"rocky:{image.context_digest()}", "claude"]


def test_run_creates_a_private_profile_home(rocky: Rocky) -> None:
    """The home holds every agent's credentials: no other host user may read it."""
    rocky("run", "-p", "foo")
    home = rocky.state / "profiles" / "foo"
    assert home.is_dir()
    assert home.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("command", [["run"], ["build"]])
def test_a_missing_docker_is_reported_without_a_traceback(
    rocky: Rocky, command: list[str]
) -> None:
    result = rocky(*command, docker=str(rocky.tmp / "no-such-docker"))
    assert result.status == 1
    assert "no-such-docker" in result.stderr
    assert "Traceback" not in result.stderr


def test_a_stale_pinned_image_runs_with_a_warning(rocky: Rocky) -> None:
    result = rocky("run", digest="stale0000")
    assert [call[0] for call in result.calls] == ["run"]
    assert "older than this Rocky" in result.stderr


def test_info_image_prints_the_tag(rocky: Rocky) -> None:
    assert rocky("info", "image").stdout == f"rocky:{image.context_digest()}\n"


def test_info_workspace_prints_where_run_mounts_the_directory(rocky: Rocky) -> None:
    project = rocky.tmp / "proj.one"
    project.mkdir()
    result = rocky("info", "workspace", cwd=project)
    assert result.stdout == f"{workspace_path(project)}\n"


def test_info_home_prints_the_profile_home_without_creating_it(
    rocky: Rocky,
) -> None:
    assert rocky("info", "home").stdout == f"{rocky.state / 'profiles' / 'main'}\n"
    assert rocky("info", "home", "-p", "work").stdout.endswith("/profiles/work\n")
    assert not (rocky.state / "profiles").exists()


def test_bare_info_prints_every_fact(rocky: Rocky) -> None:
    result = rocky("info")
    assert result.status == 0
    assert result.stdout == (
        f"workspace: {workspace_path(rocky.tmp)}\n"
        f"image: rocky:{image.context_digest()}\n"
        f"home: {rocky.state / 'profiles' / 'main'}\n"
    )


def test_ps_lists_every_container_with_its_directory(rocky: Rocky) -> None:
    containers = [
        inspected("quirky_turing", "/src/two", "work", ("pi-acp",)),
        inspected("eager_hopper", "/src/one"),
    ]
    result = rocky("ps", cwd=rocky.tmp, containers=containers)
    assert result.status == 0
    [header, *rows] = result.stdout.splitlines()
    assert header.split() == [
        "CONTAINER",
        "NAME",
        "PROFILE",
        "UP",
        "DIRECTORY",
        "COMMAND",
    ]
    assert [row.split()[1:3] for row in rows] == [
        ["eager_hopper", "main"],
        ["quirky_turing", "work"],
    ]
    assert [row.split()[4:] for row in rows] == [
        ["/src/one", "claude"],
        ["/src/two", "pi-acp"],
    ]


def test_ps_groups_by_directory_then_start_time(rocky: Rocky) -> None:
    containers = [
        inspected("late", "/src/a", started="2026-10-05T12:30:00Z"),
        inspected("other", "/src/b", started="2026-10-05T11:00:00Z"),
        inspected("early", "/src/a", started="2026-10-05T12:00:00Z"),
    ]
    rows = rocky("ps", containers=containers).stdout.splitlines()[1:]
    assert [row.split()[1] for row in rows] == ["early", "late", "other"]


def test_ps_with_nothing_running_says_so_on_stderr(rocky: Rocky) -> None:
    result = rocky("ps")
    assert result.status == 0
    assert result.stdout == ""
    assert "no Rocky containers" in result.stderr


# ------------------------------------------------------------ command line


def after_image(call: list[str]) -> list[str]:
    """The command a `docker run` call runs: everything after the image."""
    return call[call.index(f"rocky:{image.context_digest()}") + 1 :]


def home_mount(call: list[str], rocky: Rocky, profile: str) -> bool:
    home = rocky.state / "profiles" / profile
    return f"type=bind,source={home},target=/home/rocky" in call


@pytest.mark.parametrize("argv", [["--help"], ["-h"], ["help"]])
def test_help_lists_the_commands(rocky: Rocky, argv: list[str]) -> None:
    result = rocky(*argv)
    assert result.status == 0
    for command in ("run", "build", "ps", "info"):
        assert f"  {command}" in result.stdout
    assert result.calls == []


def test_each_command_has_help(rocky: Rocky) -> None:
    result = rocky("run", "--help")
    assert result.status == 0
    assert "--profile" in result.stdout
    assert result.calls == []


@pytest.mark.parametrize(
    "argv",
    [
        ["bogus"],
        ["build", "--bogus"],
        ["image"],
        ["info", "bogus"],
        ["info", "image", "extra"],
        ["info", "home", "-p", "../escape"],
        ["ps", "--all"],
        ["run", "-p"],
        ["run", "--profile"],
        ["run", "-p", "../escape"],
        ["run", "-p", "-leading-dash"],
        ["run", "--profile="],
        ["run", "--bogus"],
    ],
)
def test_a_bad_command_line_exits_2_and_starts_nothing(
    rocky: Rocky, argv: list[str]
) -> None:
    result = rocky(*argv)
    assert result.status == 2
    assert result.calls == []
    assert not (rocky.state / "profiles").exists()


def test_run_defaults_to_a_shell_in_the_main_profile(rocky: Rocky) -> None:
    [call] = rocky("run").calls
    assert after_image(call) == []
    assert home_mount(call, rocky, "main")
    assert "--publish" not in call


def test_run_options(rocky: Rocky) -> None:
    [call] = rocky("run", "-p", "work", "--login", "claude").calls
    assert after_image(call) == ["claude"]
    assert home_mount(call, rocky, "work")
    assert "--publish" in call


def test_run_profile_equals_form(rocky: Rocky) -> None:
    [call] = rocky("run", "--profile=bar", "bash").calls
    assert home_mount(call, rocky, "bar")


def test_run_options_end_at_the_command(rocky: Rocky) -> None:
    """claude has a -p of its own; only options before the command are Rocky's."""
    [call] = rocky("run", "claude", "-p", "hello", "--login").calls
    assert after_image(call) == ["claude", "-p", "hello", "--login"]
    assert home_mount(call, rocky, "main")
    assert "--publish" not in call


def test_double_dash_ends_the_options(rocky: Rocky) -> None:
    [call] = rocky("run", "--", "-weird").calls
    assert after_image(call) == ["-weird"]


def test_help_lists_run_first(rocky: Rocky) -> None:
    """Commands appear in the order the README gives them, not alphabetically."""
    commands = rocky("--help").stdout.split("Commands:")[1].split()
    assert commands[0] == "run"
