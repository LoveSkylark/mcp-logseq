from typing import Any

import pytest

from mcp_logseq_db.server import create_server


class FakeClient:
    observed_methods: frozenset[str] = frozenset()

    async def call(self, method: str, args: list[Any]) -> Any:
        return []


@pytest.mark.asyncio
async def test_server_exposes_only_verified_read_tools() -> None:
    server = create_server(FakeClient())  # type: ignore[arg-type]

    tools = await server.list_tools()

    assert {tool.name for tool in tools} == {
        "db_capabilities",
        "db_q",
        "db_custom_query",
        "db_datascript_query",
        "db_get_all_properties",
        "db_get_property",
        "db_get_all_tags",
        "db_get_tag",
        "db_get_tags_by_name",
        "db_get_tag_objects",
        "db_upsert_property",
        "db_remove_property",
        "db_create_tag",
        "db_add_tag_property",
        "db_remove_tag_property",
        "db_add_tag_extends",
        "db_remove_tag_extends",
        "db_upsert_block_property",
        "db_remove_block_property",
        "db_add_block_tag",
        "db_remove_block_tag",
        "db_set_block_icon",
        "db_remove_block_icon",
    }