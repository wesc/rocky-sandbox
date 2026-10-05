"""Reading back the containers Rocky started, and listing them."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from samples import inspected

from rocky.running import (
    MalformedInspect,
    RunningContainer,
    format_age,
    format_table,
    parse_inspect,
)

STARTED = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)


def test_parse_inspect() -> None:
    text = json.dumps([inspected("quirky_turing", "/src/proj", "work", ("pi-acp",))])
    assert parse_inspect(text) == [
        RunningContainer(
            id=b"quirky_turing".hex().ljust(64, "0"),
            name="quirky_turing",
            profile="work",
            workdir=Path("/src/proj"),
            started=STARTED.replace(microsecond=123456),
            command=("pi-acp",),
        )
    ]


def test_parse_inspect_of_nothing() -> None:
    assert parse_inspect("[]") == []


@pytest.mark.parametrize(
    "text",
    [
        "{}",
        "[1]",
        json.dumps([{"Name": "/x"}]),
        json.dumps([{**inspected("x", "/p"), "State": {"StartedAt": "yesterday"}}]),
    ],
)
def test_parse_inspect_rejects_what_docker_would_not_say(text: str) -> None:
    with pytest.raises(MalformedInspect):
        parse_inspect(text)


@pytest.mark.parametrize(
    ("seconds", "age"),
    [
        (0, "0s"),
        (59, "59s"),
        (60, "1m"),
        (3599, "59m"),
        (3600, "1h"),
        (86399, "23h"),
        (86400, "1d"),
        (-5, "0s"),
    ],
)
def test_format_age(seconds: int, age: str) -> None:
    assert format_age(timedelta(seconds=seconds)) == age


def container(name: str, workdir: str, command: tuple[str, ...]) -> RunningContainer:
    return RunningContainer(
        id=name * 20,
        name=name,
        profile="main",
        workdir=Path(workdir),
        started=STARTED,
        command=command,
    )


def test_format_table() -> None:
    table = format_table(
        [
            container("ab", "/src/one", ("claude",)),
            container("cd", "/src/two", ("sh", "-c", "a b")),
        ],
        now=STARTED + timedelta(minutes=12),
    )
    assert table.splitlines() == [
        "CONTAINER     NAME  PROFILE  UP   DIRECTORY  COMMAND",
        "abababababab  ab    main     12m  /src/one   claude",
        "cdcdcdcdcdcd  cd    main     12m  /src/two   sh -c 'a b'",
    ]
