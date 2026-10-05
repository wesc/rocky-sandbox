"""The image: its build context, the digest that tags it, and `docker build`.

The build context ships inside the package, in context/. Each build context
gets its own image, so a release and a checkout of Rocky never replace each
other's image.
"""

from __future__ import annotations

import enum
import hashlib
import subprocess
import sys
import tempfile
import time
from importlib.resources import files
from pathlib import Path
from typing import Final

from rocky.settings import Settings

# The digest of the build context an image came from. It differs from this
# Rocky's only when ROCKY_IMAGE pins a tag.
CONTEXT_LABEL: Final = "rocky.context"

REPOSITORY: Final = "rocky"

# In the order the digest covers them.
CONTEXT_FILES: Final = ("Dockerfile", "entrypoint.sh")


class Status(enum.Enum):
    MISSING = enum.auto()
    STALE = enum.auto()
    """Built from another build context. Possible only when ROCKY_IMAGE pins a tag."""
    CURRENT = enum.auto()


def context_files() -> dict[str, bytes]:
    context = files("rocky").joinpath("context")
    return {name: context.joinpath(name).read_bytes() for name in CONTEXT_FILES}


def context_digest() -> str:
    digest = hashlib.sha256()
    for contents in context_files().values():
        digest.update(contents)
    return digest.hexdigest()[:16]


def tag(settings: Settings) -> str:
    return settings.image_override or f"{REPOSITORY}:{context_digest()}"


def write_context(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, contents in context_files().items():
        (directory / name).write_bytes(contents)


def built_from(settings: Settings) -> str | None:
    """The context digest the image was built from, or None if it is not built."""
    inspect = subprocess.run(
        [
            settings.docker,
            "image",
            "inspect",
            "-f",
            f'{{{{index .Config.Labels "{CONTEXT_LABEL}"}}}}',
            tag(settings),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return inspect.stdout.strip() if inspect.returncode == 0 else None


def status(settings: Settings) -> Status:
    digest = built_from(settings)
    if digest is None:
        return Status.MISSING
    if digest != context_digest():
        return Status.STALE
    return Status.CURRENT


def build(settings: Settings, *, update: bool) -> int:
    """Run `docker build` and return its exit status.

    With update, pull the base image and rebuild the agent layers. The
    toolchain layers come from the cache.
    """
    image = tag(settings)
    print(f"rocky: building {image}", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="rocky-build-") as tmp:
        context = Path(tmp)
        write_context(context)
        docker_build = [settings.docker, "build"]
        docker_build += ["--label", f"{CONTEXT_LABEL}={context_digest()}"]
        docker_build += ["--tag", image]
        if update:
            docker_build += ["--pull"]
            docker_build += ["--build-arg", f"AGENTS_REFRESH={int(time.time())}"]
        docker_build += [str(context)]
        return subprocess.run(docker_build, check=False).returncode
