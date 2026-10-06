"""The `rocky` command: a click group with one command per thing Rocky does."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Final, NoReturn, override

import click
from click.decorators import FC

from rocky import container, image, running
from rocky.container import DEFAULT_PROFILE, Caller, ProfileName, RunRequest
from rocky.settings import Settings

CONTEXT_SETTINGS: Final = {"help_option_names": ["-h", "--help"]}


class CommandsInOrder(click.Group):
    """Lists commands in the order this file defines them, not alphabetically."""

    @override
    def list_commands(self, ctx: click.Context) -> list[str]:
        return list(self.commands)


@click.group(
    cls=CommandsInOrder,
    context_settings=CONTEXT_SETTINGS,
    invoke_without_command=True,
)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Rocky: a sandboxed container for coding agents.

    `rocky run` mounts $PWD at /workspace-<name>-<hash> and starts there, with
    the profile's home, ~/.rocky/profiles/NAME, at /home/rocky.
    """
    ctx.obj = Settings.from_environ()
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def valid_profile(
    _ctx: click.Context, _param: click.Parameter, name: str
) -> ProfileName:
    try:
        return container.profile_name(name)
    except container.InvalidProfileName as error:
        raise click.BadParameter(str(error)) from None


def profile_option(help_text: str) -> Callable[[FC], FC]:
    return click.option(
        "-p",
        "--profile",
        default=DEFAULT_PROFILE,
        show_default=True,
        metavar="NAME",
        callback=valid_profile,
        help=help_text,
    )


# Options stop at the command, so `rocky run claude -p hi` gives -p to claude.
# See test_run_options_end_at_the_command.
@cli.command("run", context_settings={"allow_interspersed_args": False})
@profile_option("Run with this profile's home.")
@click.option(
    "--login",
    is_flag=True,
    help="Publish the OAuth callback port that `claude` logs in on.",
)
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
@click.pass_obj
def run_cmd(
    settings: Settings, profile: ProfileName, login: bool, command: tuple[str, ...]
) -> None:
    """Open a shell, or run COMMAND, in a container over $PWD.

    Put `--` before a COMMAND that starts with a dash.
    """
    start_container(settings, RunRequest(profile, login, command))


@cli.command("build")
@click.option(
    "--update", is_flag=True, help="Pull the base image and reinstall the agents."
)
@click.pass_obj
def build_cmd(settings: Settings, update: bool) -> None:
    """Build the image; needed before the first run."""
    sys.exit(image.build(settings, update=update))


@cli.command("ps")
@click.pass_obj
def ps_cmd(settings: Settings) -> None:
    """List Rocky's containers and their directories."""
    sys.exit(print_containers(settings))


@cli.group("info", cls=CommandsInOrder, invoke_without_command=True)
@click.pass_context
def info_group(ctx: click.Context) -> None:
    """Print facts about Rocky, or the one named.

    Bare `rocky info` prints each fact as `name: value`. A subcommand prints
    only the value, for scripts.
    """
    if ctx.invoked_subcommand is None:
        settings = ctx.ensure_object(Settings)
        click.echo(f"workspace: {workspace()}")
        click.echo(f"image: {image.tag(settings)}")
        click.echo(f"home: {container.profile_home(settings, DEFAULT_PROFILE)}")


@info_group.command("workspace")
def info_workspace_cmd() -> None:
    """Print where `rocky run` mounts $PWD in the container."""
    click.echo(workspace())


@info_group.command("image")
@click.pass_obj
def info_image_cmd(settings: Settings) -> None:
    """Print the tag of the image this Rocky runs."""
    click.echo(image.tag(settings))


@info_group.command("home")
@profile_option("Print this profile's home.")
@click.pass_obj
def info_home_cmd(settings: Settings, profile: ProfileName) -> None:
    """Print the host directory mounted at /home/rocky."""
    click.echo(container.profile_home(settings, profile))


@cli.command("print-context")
@click.argument("directory", type=click.Path(path_type=Path))
def print_context_cmd(directory: Path) -> None:
    """Write the Dockerfile and entrypoint to DIRECTORY."""
    image.write_context(directory)


@cli.command("help")
@click.pass_context
def help_cmd(ctx: click.Context) -> None:
    """Show this message."""
    if ctx.parent is not None:
        click.echo(ctx.parent.get_help())


def start_container(settings: Settings, request: RunRequest) -> NoReturn:
    """Become `docker run`, or exit 1 if the image is not built.

    A build takes minutes, so Rocky never starts one on its own.
    """
    tag = image.tag(settings)
    match image.status(settings):
        case image.Status.MISSING:
            warn(f"image {tag} does not exist yet -- run `rocky build`")
            sys.exit(1)
        case image.Status.STALE:
            warn(f"{tag} is older than this Rocky -- run `rocky build`")
        case image.Status.CURRENT:
            pass
    # The home holds every agent's credentials.
    # See test_run_creates_a_private_profile_home.
    home = container.profile_home(settings, request.profile)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    argv = container.docker_run_argv(settings, Caller.current(), tag, request)
    os.execvp(argv[0], argv)


def workspace() -> PurePosixPath:
    return container.workspace_path(Caller.current().workdir)


def print_containers(settings: Settings) -> int:
    """Print every running Rocky container, grouped by directory.

    Returns the exit status.
    """
    try:
        found = running.containers(settings)
    except running.DockerFailed as error:
        warn(str(error))
        return error.status
    if not found:
        warn("no Rocky containers are running")
        return 0
    found.sort(key=lambda each: (str(each.workdir), each.started))
    click.echo(running.format_table(found, now=datetime.now(UTC)), nl=False)
    return 0


def warn(message: str) -> None:
    click.echo(f"rocky: {message}", err=True)


def main() -> None:
    """The entry point. click exits with each command's status."""
    try:
        cli()
    except FileNotFoundError as error:
        docker = Settings.from_environ().docker
        if error.filename != docker:
            raise
        warn(f"cannot run {docker}: install docker, or set ROCKY_DOCKER")
        sys.exit(1)
