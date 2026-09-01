from collections import deque
from typing import Any

import httpx
import pytest

from mcp_logseq_db.mutations import VerifiedMutations


IDENT = ":user.property/status"
PROPERTY_UUID = "12345678-1234-5678-1234-567812345678"
TAG_UUID = "87654321-4321-8765-4321-876543218765"


class RecordingClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = deque(responses)
        self.calls: list[tuple[str, list[Any]]] = []

    async def call(self, method: str, args: list[Any]) -> Any:
        self.calls.append((method, args))
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_upsert_property_writes_and_reads_back_exact_ident() -> None:
    client = RecordingClient([{"ident": IDENT}, {"ident": IDENT}])

    result = await VerifiedMutations(client).upsert_property(  # type: ignore[arg-type]
        "Status", {"type": "default"}
    )

    assert result.verified_state == {"ident": IDENT}
    assert client.calls == [
        ("logseq.DB.upsertProperty", ["Status", {"type": "default"}, {}]),
        ("logseq.DB.getProperty", [IDENT]),
    ]


@pytest.mark.asyncio
async def test_timed_out_upsert_is_resolved_by_read_back() -> None:
    client = RecordingClient([httpx.ReadTimeout("ambiguous")])

    with pytest.raises(RuntimeError, match="generated ident"):
        await VerifiedMutations(client).upsert_property(  # type: ignore[arg-type]
            "Status", {"type": "default"}
        )


@pytest.mark.asyncio
async def test_remove_requires_exact_ident_and_verifies_absence() -> None:
    client = RecordingClient([{"db/ident": IDENT}, {"ok": True}, None])
    mutations = VerifiedMutations(client)  # type: ignore[arg-type]

    result = await mutations.remove_property(IDENT)

    assert result.verified_state is None
    assert client.calls[1] == ("logseq.DB.removeProperty", [IDENT])

    with pytest.raises(ValueError, match="exact namespaced property ident"):
        await mutations.remove_property("Status")


@pytest.mark.asyncio
async def test_remove_tag_property_resolves_ident_to_property_uuid() -> None:
    client = RecordingClient([
        {"ident": IDENT, "id": 42, "uuid": PROPERTY_UUID},
        None,
        {"uuid": TAG_UUID, ":logseq.property.class/properties": []},
    ])

    await VerifiedMutations(client).remove_tag_property(TAG_UUID, IDENT)  # type: ignore[arg-type]

    assert client.calls[1] == (
        "logseq.DB.removeTagProperty",
        [TAG_UUID, PROPERTY_UUID],
    )


@pytest.mark.asyncio
async def test_block_mutations_require_exact_uuid() -> None:
    mutations = VerifiedMutations(RecordingClient([]))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="exact UUID"):
        await mutations.remove_block_icon("fuzzy block title")


@pytest.mark.asyncio
async def test_icon_type_is_restricted() -> None:
    mutations = VerifiedMutations(RecordingClient([]))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="icon_type"):
        await mutations.set_block_icon(TAG_UUID, "image", "file.png")


@pytest.mark.asyncio
async def test_emoji_verification_accepts_normalized_stored_id() -> None:
    client = RecordingClient([
        None,
        {"uuid": TAG_UUID, ":logseq.property/icon": {"type": "emoji", "id": "test_tube"}},
    ])

    result = await VerifiedMutations(client).set_block_icon(  # type: ignore[arg-type]
        TAG_UUID, "emoji", "Test Tube"
    )

    assert result.verified_state[":logseq.property/icon"]["id"] == "test_tube"