import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from mcp_logseq_db.client import ALLOWED_METHODS, LogseqDBClient, LogseqProtocolError


Outcome = httpx.Response | Exception | Callable[[], Awaitable[httpx.Response]]


class ScriptedClient:
    def __init__(self, outcomes: list[Outcome], lifecycle: list[str], **_: Any) -> None:
        self._outcomes = outcomes
        self._lifecycle = lifecycle
        lifecycle.append("created")

    async def __aenter__(self) -> "ScriptedClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        self._lifecycle.append("closed")

    async def post(self, url: str, **_: Any) -> httpx.Response:
        outcome = self._outcomes.pop(0)
        if callable(outcome):
            return await outcome()
        if isinstance(outcome, Exception):
            raise outcome
        outcome.request = httpx.Request("POST", url)
        return outcome


def make_client(outcomes: list[Outcome], lifecycle: list[str]) -> LogseqDBClient:
    return LogseqDBClient(
        "http://127.0.0.1:12315",
        "token",
        client_factory=lambda **kwargs: ScriptedClient(outcomes, lifecycle, **kwargs),
    )


def test_every_allowed_method_is_in_db_namespace() -> None:
    assert ALLOWED_METHODS
    assert all(method.startswith("logseq.DB.") for method in ALLOWED_METHODS)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method",
    ["logseq.cli.listPages", "logseq.App.getCurrentGraph", "logseq.Editor.getPage"],
)
async def test_non_db_namespaces_are_rejected(method: str) -> None:
    client = make_client([], [])

    with pytest.raises(ValueError, match="DB API method is not allowed"):
        await client.call(method, [])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method",
    ["logseq.DB.getFavorites", "logseq.DB.setPropertyNodeTags"],
)
async def test_live_rejected_db_methods_are_blocked(method: str) -> None:
    client = make_client([], [])

    with pytest.raises(ValueError, match="DB API method is not allowed"):
        await client.call(method, [])


@pytest.mark.asyncio
async def test_timeout_does_not_poison_next_request() -> None:
    outcomes: list[Outcome] = [
        httpx.Response(200, json={"ok": 1}),
        httpx.ReadTimeout("intentional timeout"),
        httpx.Response(200, json={"ok": 2}),
    ]
    lifecycle: list[str] = []
    client = make_client(outcomes, lifecycle)

    assert await client.call("logseq.DB.getAllProperties", []) == {"ok": 1}
    with pytest.raises(httpx.ReadTimeout):
        await client.call("logseq.DB.getAllProperties", [])
    assert await client.call("logseq.DB.getAllProperties", []) == {"ok": 2}
    assert lifecycle == ["created", "closed"] * 3


@pytest.mark.asyncio
async def test_cancelled_request_does_not_poison_next_request() -> None:
    started = asyncio.Event()

    async def interrupted() -> httpx.Response:
        started.set()
        await asyncio.Future()
        raise AssertionError("unreachable")

    outcomes: list[Outcome] = [interrupted, httpx.Response(200, json={"ok": True})]
    lifecycle: list[str] = []
    client = make_client(outcomes, lifecycle)

    task = asyncio.create_task(client.call("logseq.DB.getAllProperties", []))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await client.call("logseq.DB.getAllProperties", []) == {"ok": True}
    assert lifecycle == ["created", "closed"] * 2


@pytest.mark.asyncio
async def test_malformed_response_does_not_poison_next_request() -> None:
    outcomes: list[Outcome] = [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={"ok": True}),
    ]
    lifecycle: list[str] = []
    client = make_client(outcomes, lifecycle)

    with pytest.raises(LogseqProtocolError, match="malformed JSON"):
        await client.call("logseq.DB.getAllProperties", [])
    assert await client.call("logseq.DB.getAllProperties", []) == {"ok": True}
    assert lifecycle == ["created", "closed"] * 2