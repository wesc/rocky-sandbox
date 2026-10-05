"""The ROCKY_* environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Rocky's configuration. An empty variable counts as unset."""

    image_override: str | None
    """A fixed image tag to build and run, in place of the one per build context."""

    state_dir: Path
    """The host directory that holds Rocky's state: its profiles."""

    docker: str
    """The container CLI to invoke, as a command name or a path."""

    @property
    def profiles_dir(self) -> Path:
        """Where each profile's home directory lives, one per subdirectory."""
        return self.state_dir / "profiles"

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] = os.environ) -> Settings:
        state_dir = environ.get("ROCKY_STATE_DIR") or "~/.rocky"
        return cls(
            image_override=environ.get("ROCKY_IMAGE") or None,
            # Absolute, because docker reads a relative mount source as the
            # name of a volume rather than a path.
            state_dir=Path(state_dir).expanduser().absolute(),
            docker=environ.get("ROCKY_DOCKER") or "docker",
        )
