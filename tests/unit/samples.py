"""Sample data shared by the unit tests."""


def inspected(
    name: str,
    workdir: str,
    profile: str = "main",
    command: tuple[str, ...] = ("claude",),
    started: str = "2026-10-05T12:00:00.123456789Z",
) -> dict[str, object]:
    """One container as `docker inspect` describes it, cut to the fields Rocky reads."""
    return {
        "Id": name.encode().hex().ljust(64, "0"),
        "Name": f"/{name}",
        "Config": {
            "Cmd": list(command),
            "Labels": {"rocky.workdir": workdir, "rocky.profile": profile},
        },
        "State": {"StartedAt": started},
    }
