"""The build context, its digest, the image tag, and settings."""

from pathlib import Path

import pytest

from rocky import image
from rocky.settings import Settings


def settings(image_override: str | None = None) -> Settings:
    return Settings(image_override=image_override, state_dir=Path("/s"), docker="d")


def test_context_is_the_dockerfile_and_entrypoint() -> None:
    context = image.context_files()
    assert set(context) == {"Dockerfile", "entrypoint.sh"}
    assert context["Dockerfile"].startswith(b"FROM ")
    assert context["entrypoint.sh"].startswith(b"#!/usr/bin/env bash\n")


def test_write_context_writes_it_unchanged(tmp_path: Path) -> None:
    image.write_context(tmp_path / "out")
    for name, contents in image.context_files().items():
        assert (tmp_path / "out" / name).read_bytes() == contents


def test_digest_is_stable_and_short() -> None:
    digest = image.context_digest()
    assert digest == image.context_digest()
    assert len(digest) == 16
    int(digest, 16)


def test_tag_is_named_for_the_digest() -> None:
    assert image.tag(settings()) == f"rocky:{image.context_digest()}"


def test_rocky_image_pins_the_tag() -> None:
    assert image.tag(settings("mine:dev")) == "mine:dev"


def test_settings_defaults() -> None:
    defaults = Settings.from_environ({})
    assert defaults.image_override is None
    assert defaults.state_dir == Path.home() / ".rocky"
    assert defaults.docker == "docker"
    assert defaults.profiles_dir == Path.home() / ".rocky" / "profiles"


def test_settings_from_the_environment() -> None:
    configured = Settings.from_environ(
        {"ROCKY_IMAGE": "x:y", "ROCKY_STATE_DIR": "/st", "ROCKY_DOCKER": "podman"}
    )
    assert configured == Settings(
        image_override="x:y", state_dir=Path("/st"), docker="podman"
    )


def test_empty_variables_count_as_unset() -> None:
    empty = {"ROCKY_IMAGE": "", "ROCKY_STATE_DIR": "", "ROCKY_DOCKER": ""}
    assert Settings.from_environ(empty) == Settings.from_environ({})


def test_a_relative_state_dir_is_made_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docker reads a relative mount source as a volume name, not a path."""
    monkeypatch.chdir(tmp_path)
    configured = Settings.from_environ({"ROCKY_STATE_DIR": "state"})
    assert configured.state_dir == tmp_path / "state"


def test_the_state_dir_expands_a_tilde() -> None:
    configured = Settings.from_environ({"ROCKY_STATE_DIR": "~/elsewhere"})
    assert configured.state_dir == Path.home() / "elsewhere"
