"""Failure-isolated client for the Logseq DB HTTP API."""

from collections.abc import Callable
from typing import Any

import httpx


ALLOWED_METHODS = frozenset({
    "logseq.DB.q",
    "logseq.DB.customQuery",
    "logseq.DB.datascriptQuery",
    "logseq.DB.getProperty",
    "logseq.DB.getAllProperties",
    "logseq.DB.getAllTags",
    "logseq.DB.getTagObjects",
    "logseq.DB.getTag",
    "logseq.DB.getTagsByName",
    "logseq.DB.upsertProperty",
    "logseq.DB.removeProperty",
    "logseq.DB.upsertBlockProperty",
    "logseq.DB.removeBlockProperty",
    "logseq.DB.createTag",
    "logseq.DB.addTagProperty",
    "logseq.DB.removeTagProperty",
    "logseq.DB.addTagExtends",
    "logseq.DB.removeTagExtends",
    "logseq.DB.addBlockTag",
    "logseq.DB.removeBlockTag",
    "logseq.DB.setBlockIcon",
    "logseq.DB.removeBlockIcon",
    "logseq.DB.addPropertyValueChoices",
    "logseq.DB.getFileContent",
    "logseq.DB.setFileContent",
})

WRITE_METHODS = frozenset({
    "logseq.DB.upsertProperty",
    "logseq.DB.removeProperty",
    "logseq.DB.upsertBlockProperty",
    "logseq.DB.removeBlockProperty",
    "logseq.DB.createTag",
    "logseq.DB.addTagProperty",
    "logseq.DB.removeTagProperty",
    "logseq.DB.addTagExtends",
    "logseq.DB.removeTagExtends",
    "logseq.DB.addBlockTag",
    "logseq.DB.removeBlockTag",
    "logseq.DB.setBlockIcon",
    "logseq.DB.removeBlockIcon",
    "logseq.DB.addPropertyValueChoices",
    "logseq.DB.setFileContent",
})

# Promoted only after live response-shape, read-back, cleanup, and MCP testing
# against Logseq 2.0.1 on 2026-09-01.
VERIFIED_WRITE_METHODS = frozenset({
    "logseq.DB.upsertProperty",
    "logseq.DB.removeProperty",
    "logseq.DB.upsertBlockProperty",
    "logseq.DB.removeBlockProperty",
    "logseq.DB.createTag",
    "logseq.DB.addTagProperty",
    "logseq.DB.removeTagProperty",
    "logseq.DB.addTagExtends",
    "logseq.DB.removeTagExtends",
    "logseq.DB.addBlockTag",
    "logseq.DB.removeBlockTag",
    "logseq.DB.setBlockIcon",
    "logseq.DB.removeBlockIcon",
})


class LogseqProtocolError(RuntimeError):
    """Raised when Logseq returns a response that is not valid API JSON."""


ClientFactory = Callable[..., httpx.AsyncClient]


class LogseqDBClient:
    """Call Logseq with a fresh, deterministically closed client per request."""

    def __init__(
        self,
        base_url: str,
        api_token: str,
        *,
        connect_timeout: float = 3.0,
        read_timeout: float = 15.0,
        verify_ssl: bool = True,
        client_factory: ClientFactory = httpx.AsyncClient,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/api"
        self._api_token = api_token
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=read_timeout,
            pool=connect_timeout,
        )
        self._verify_ssl = verify_ssl
        self._client_factory = client_factory
        self._observed_methods: set[str] = set()

    @property
    def observed_methods(self) -> frozenset[str]:
        return frozenset(self._observed_methods)

    async def call(self, method: str, args: list[Any]) -> Any:
        if method not in ALLOWED_METHODS:
            raise ValueError(f"Logseq DB API method is not allowed: {method!r}")
        if not isinstance(args, list):
            raise TypeError("Logseq API args must be a list")

        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Connection": "close",
        }
        async with self._client_factory(
            timeout=self._timeout,
            verify=self._verify_ssl,
            headers=headers,
        ) as client:
            response = await client.post(
                self._url,
                json={"method": method, "args": args},
            )
            response.raise_for_status()
            try:
                result = response.json()
            except ValueError as error:
                raise LogseqProtocolError(
                    f"{method} returned malformed JSON"
                ) from error
            self._observed_methods.add(method)
            return result