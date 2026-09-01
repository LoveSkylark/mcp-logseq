from typing import Any

import pytest

from mcp_logseq_db.capabilities import CapabilityDiscovery


class ProbeClient:
    observed_methods: frozenset[str] = frozenset()

    async def call(self, method: str, args: list[Any]) -> Any:
        return []


@pytest.mark.asyncio
async def test_fresh_capabilities_report_live_verified_writes() -> None:
    capabilities = await CapabilityDiscovery(ProbeClient()).discover()  # type: ignore[arg-type]

    assert capabilities.db_version is None
    assert capabilities.supported_entity_types == ("property", "tag")
    assert "logseq.DB.upsertProperty" in capabilities.supported_write_operations
    assert "logseq.DB.addBlockTag" in capabilities.supported_write_operations
    assert "logseq.DB.removeProperty" in capabilities.supported_removal_operations
    assert capabilities.supported_query_features == (
        "datascript",
        "datalog",
        "custom-query",
    )
    assert capabilities.candidate_write_operations == (
        "logseq.DB.addPropertyValueChoices",
        "logseq.DB.setFileContent",
    )
    assert capabilities.unavailable_over_http == (
        "logseq.DB.onChanged",
        "logseq.DB.onBlockChanged",
        "logseq.DB.getFavorites",
        "logseq.DB.setPropertyNodeTags",
    )