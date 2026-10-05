"""rocky run, end to end: the CLI, then the image's entrypoint, then the command."""

from __future__ import annotations

import json
import os
import signal
import subprocess

import pytest
from conftest import LINUX, MAC, ROOT, STRAY, Caller, Host, MakeHost, image_env, owner

from rocky.container import workspace_path

# --------------------------------------------------------------- identity


@pytest.mark.parametrize("caller", [MAC, LINUX], ids=lambda c: c.name)
def test_the_command_runs_as_the_caller(make: MakeHost, caller: Caller) -> None:
    host = make(caller)
    out = host.run("sh", "-c", "id -u; id -g; echo $HOME; echo $PWD")
    assert out.splitlines() == [
        str(caller.uid),
        str(caller.gid),
        "/home/rocky",
        str(workspace_path(host.project)),
    ]


def test_a_root_caller_stays_root_with_the_profile_home(make: MakeHost) -> None:
    host = make(ROOT)
    assert host.run("sh", "-c", "id -u; echo $HOME").split() == ["0", "/home/rocky"]
    assert (host.home() / ".bashrc").is_file()


def test_the_container_marks_itself_as_rocky(mac: Host) -> None:
    """Programs inside test for /.rockyenv, as they test for /.dockerenv."""
    assert mac.rocky("run", "test", "-e", "/.rockyenv").returncode == 0


def test_the_exit_status_is_the_commands(mac: Host) -> None:
    assert mac.rocky("run", "sh", "-c", "exit 7").returncode == 7


def test_the_image_matches_the_checkout(mac: Host) -> None:
    """A mismatch would mean scripts/integration.sh ran a stale image."""
    result = mac.rocky("run", "true")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


# ------------------------------------------------------- workspace and home


def test_files_made_in_the_workspace_belong_to_the_caller(mac: Host) -> None:
    mac.run("sh", "-c", "echo made > made-here")
    made = mac.project / "made-here"
    assert made.read_text() == "made\n"
    assert owner(made) == (MAC.uid, MAC.gid)


def test_a_new_profile_home_is_seeded_and_owned(mac: Host) -> None:
    mac.run("true")
    bashrc = mac.home() / ".bashrc"
    assert bashrc.is_file()
    assert owner(bashrc) == (MAC.uid, MAC.gid)
    assert owner(mac.home()) == (MAC.uid, MAC.gid)


def test_a_login_survives_into_the_next_container(mac: Host) -> None:
    mac.run("sh", "-c", "mkdir -p ~/.agent && echo tok-abc123 > ~/.agent/creds")
    creds = mac.home() / ".agent" / "creds"
    assert owner(creds) == (MAC.uid, MAC.gid)
    assert mac.run("cat", "/home/rocky/.agent/creds") == "tok-abc123\n"


def test_an_existing_home_is_not_reseeded(mac: Host) -> None:
    mac.run("true")
    mac.write(mac.home() / ".bashrc", "# mine\n")
    mac.run("true")
    assert (mac.home() / ".bashrc").read_text() == "# mine\n"


def test_profiles_do_not_see_each_others_homes(mac: Host) -> None:
    mac.run("sh", "-c", "echo secret > ~/creds")
    assert mac.rocky("run", "-p", "other", "cat", "/home/rocky/creds").returncode != 0
    assert not (mac.home("other") / "creds").exists()


# ---------------------------------------------------- stdin, stdout, PATH


def test_stdin_reaches_the_command(mac: Host) -> None:
    assert mac.run("cat", stdin="hello\n") == "hello\n"


def test_rc_file_path_without_rc_file_output(mac: Host) -> None:
    """A tool on the PATH an installer added to ~/.bashrc, run without a shell.

    The PATH line goes below the stock bashrc's early return for
    non-interactive shells, as installers put it, and the bashrc is chatty:
    none of that chatter may reach the command's stdout.
    """
    mac.run("true")
    tool = mac.home() / "rcbin" / "rctool"
    mac.write(tool, '#!/bin/sh\necho "rctool read: $(cat)"\n')
    tool.chmod(0o755)
    bashrc = mac.home() / ".bashrc"
    mac.write(
        bashrc,
        bashrc.read_text() + 'echo "chatty bashrc"\nexport PATH="$HOME/rcbin:$PATH"\n',
    )
    assert mac.run("rctool", stdin="hello") == "rctool read: hello\n"


def test_a_bashrc_that_bails_leaves_the_image_path(mac: Host) -> None:
    mac.run("true")
    mac.write(mac.home() / ".bashrc", "exit 3\n")
    assert mac.run("printenv", "PATH") == image_env()["PATH"] + "\n"


# --------------------------------------------------------------- toolchains

# The uid that will own a container is not known until it starts, so the
# toolchains have to be writable by any uid rather than owned by one: the agent
# is expected to `npm install -g`, `claude update`, `uv self update` and
# rustup without sudo.
TOOLCHAIN_DIRS = {
    "npm installs globally": "/opt/node/lib/node_modules",
    "an agent replaces its own binary": "/opt/node/bin",
    "nvm installs another node": "/opt/nvm/versions/node",
    "uv updates itself": "/opt/uv/bin",
    "rustup updates its toolchains": "/opt/rustup",
    "cargo writes its registry cache": "/opt/cargo",
}


@pytest.mark.parametrize("directory", TOOLCHAIN_DIRS.values(), ids=TOOLCHAIN_DIRS)
def test_toolchains_are_writable_by_any_uid(make: MakeHost, directory: str) -> None:
    host = make(STRAY)
    probe = f"{directory}/.rocky-write-probe"
    host.run("sh", "-c", f"touch {probe} && rm {probe}")


# ------------------------------------------------------------ ACP adapters

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {"protocolVersion": 1, "clientCapabilities": {}},
}


@pytest.mark.parametrize("adapter", ["pi-acp", "claude-agent-acp"])
def test_an_acp_adapter_answers_over_rocky_run(mac: Host, adapter: str) -> None:
    """An editor's view of Rocky: the adapter's stdout must be pure protocol.

    initialize needs no login or model, so this runs offline. Anything an rc
    file or Rocky itself printed to stdout would break the first line.
    """
    process = subprocess.Popen(
        mac.command("run", adapter),
        cwd=mac.project,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        out, err = process.communicate(json.dumps(INITIALIZE) + "\n", timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        out, err = process.communicate()
    first = out.splitlines()[0] if out else ""
    assert first.startswith("{"), f"stdout: {out!r}\nstderr: {err}"
    reply = json.loads(first)
    assert reply["id"] == 0
    assert reply["result"]["protocolVersion"] == 1
