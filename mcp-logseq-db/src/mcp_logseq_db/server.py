"""Runnable MCP server exposing only live-verified Logseq DB reads."""

from typing import Any

from mcp.server import MCPServer

from .capabilities import CapabilityDiscovery
from .client import LogseqDBClient
from .mutations import VerifiedMutations
from .settings import Settings


def create_server(client: LogseqDBClient) -> MCPServer:
    server = MCPServer(
        "mcp-logseq-db",
        description="Narrow DB-native MCP server for Logseq 2.x",
        instructions=(
            "Use exact DB identifiers. Only live-verified logseq.DB reads are "
            "exposed; unsupported and untested operations are unavailable."
        ),
    )

    @server.tool(name="db_capabilities", structured_output=True)
    async def db_capabilities() -> dict[str, Any]:
        """Probe and report DB methods supported by the connected instance."""
        return (await CapabilityDiscovery(client).discover()).to_dict()

    @server.tool(name="db_q")
    async def db_q(query: str) -> Any:
        """Run a query through logseq.DB.q."""
        return await client.call("logseq.DB.q", [query])

    @server.tool(name="db_custom_query")
    async def db_custom_query(query: str) -> Any:
        """Run a custom query through logseq.DB.customQuery."""
        return await client.call("logseq.DB.customQuery", [query])

    @server.tool(name="db_datascript_query")
    async def db_datascript_query(query: str) -> Any:
        """Run a read-only Datascript query through logseq.DB.datascriptQuery."""
        return await client.call("logseq.DB.datascriptQuery", [query])

    @server.tool(name="db_get_all_properties")
    async def db_get_all_properties() -> Any:
        """Return all DB property definitions."""
        return await client.call("logseq.DB.getAllProperties", [])

    @server.tool(name="db_get_property")
    async def db_get_property(property_ident: str) -> Any:
        """Get a property by its exact namespaced ident."""
        if not property_ident.startswith(":") or "/" not in property_ident:
            raise ValueError("property_ident must be an exact namespaced ident")
        return await client.call("logseq.DB.getProperty", [property_ident])

    @server.tool(name="db_get_all_tags")
    async def db_get_all_tags() -> Any:
        """Return all DB tags/classes."""
        return await client.call("logseq.DB.getAllTags", [])

    @server.tool(name="db_get_tag")
    async def db_get_tag(identifier: str) -> Any:
        """Get a tag by exact ident, UUID, or title."""
        return await client.call("logseq.DB.getTag", [identifier])

    @server.tool(name="db_get_tags_by_name")
    async def db_get_tags_by_name(title: str) -> Any:
        """Get tags matching an exact title."""
        return await client.call("logseq.DB.getTagsByName", [title])

    @server.tool(name="db_get_tag_objects")
    async def db_get_tag_objects(identifier: str) -> Any:
        """Return objects associated with a tag ident, UUID, or title."""
        return await client.call("logseq.DB.getTagObjects", [identifier])

    @server.tool(name="db_upsert_property", structured_output=True)
    async def db_upsert_property(
        title: str,
        schema: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update a property and verify it by its returned exact ident."""
        result = await VerifiedMutations(client).upsert_property(
            title, schema, options
        )
        return result.to_dict()

    @server.tool(name="db_remove_property", structured_output=True)
    async def db_remove_property(property_ident: str) -> dict[str, Any]:
        """Remove an exact property ident and verify that it is absent."""
        result = await VerifiedMutations(client).remove_property(property_ident)
        return result.to_dict()

    @server.tool(name="db_create_tag", structured_output=True)
    async def db_create_tag(
        title: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Create a tag and verify it through its returned exact identity."""
        return (await VerifiedMutations(client).create_tag(title, options)).to_dict()

    @server.tool(name="db_add_tag_property", structured_output=True)
    async def db_add_tag_property(tag_uuid: str, property_ident: str) -> dict[str, Any]:
        """Add an exact property to an exact tag UUID and verify the relation."""
        return (
            await VerifiedMutations(client).add_tag_property(tag_uuid, property_ident)
        ).to_dict()

    @server.tool(name="db_remove_tag_property", structured_output=True)
    async def db_remove_tag_property(tag_uuid: str, property_ident: str) -> dict[str, Any]:
        """Remove an exact property from an exact tag UUID and verify removal."""
        return (
            await VerifiedMutations(client).remove_tag_property(tag_uuid, property_ident)
        ).to_dict()

    @server.tool(name="db_add_tag_extends", structured_output=True)
    async def db_add_tag_extends(tag_uuid: str, parent_tag_uuid: str) -> dict[str, Any]:
        """Add and verify inheritance between two exact tag UUIDs."""
        return (
            await VerifiedMutations(client).add_tag_extends(tag_uuid, parent_tag_uuid)
        ).to_dict()

    @server.tool(name="db_remove_tag_extends", structured_output=True)
    async def db_remove_tag_extends(tag_uuid: str, parent_tag_uuid: str) -> dict[str, Any]:
        """Remove and verify inheritance between two exact tag UUIDs."""
        return (
            await VerifiedMutations(client).remove_tag_extends(tag_uuid, parent_tag_uuid)
        ).to_dict()

    @server.tool(name="db_upsert_block_property", structured_output=True)
    async def db_upsert_block_property(
        block_uuid: str,
        property_ident: str,
        value: Any,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Set an exact property on an exact block UUID and verify its presence."""
        return (
            await VerifiedMutations(client).upsert_block_property(
                block_uuid, property_ident, value, options
            )
        ).to_dict()

    @server.tool(name="db_remove_block_property", structured_output=True)
    async def db_remove_block_property(
        block_uuid: str, property_ident: str
    ) -> dict[str, Any]:
        """Remove an exact property from a block UUID and verify its absence."""
        return (
            await VerifiedMutations(client).remove_block_property(
                block_uuid, property_ident
            )
        ).to_dict()

    @server.tool(name="db_add_block_tag", structured_output=True)
    async def db_add_block_tag(block_uuid: str, tag_uuid: str) -> dict[str, Any]:
        """Add an exact tag UUID to an exact block UUID and verify the relation."""
        return (
            await VerifiedMutations(client).add_block_tag(block_uuid, tag_uuid)
        ).to_dict()

    @server.tool(name="db_remove_block_tag", structured_output=True)
    async def db_remove_block_tag(block_uuid: str, tag_uuid: str) -> dict[str, Any]:
        """Remove an exact tag UUID from a block UUID and verify its absence."""
        return (
            await VerifiedMutations(client).remove_block_tag(block_uuid, tag_uuid)
        ).to_dict()

    @server.tool(name="db_set_block_icon", structured_output=True)
    async def db_set_block_icon(
        block_uuid: str, icon_type: str, icon_name: str
    ) -> dict[str, Any]:
        """Set and verify an icon. For emoji, use its case-sensitive emoji-mart display name, such as 'Test Tube' or 'Books', not a glyph or ID."""
        return (
            await VerifiedMutations(client).set_block_icon(
                block_uuid, icon_type, icon_name
            )
        ).to_dict()

    @server.tool(name="db_remove_block_icon", structured_output=True)
    async def db_remove_block_icon(block_uuid: str) -> dict[str, Any]:
        """Remove an icon from an exact block UUID and verify its absence."""
        return (await VerifiedMutations(client).remove_block_icon(block_uuid)).to_dict()

    return server


def main() -> None:
    settings = Settings.from_env()
    client = LogseqDBClient(
        settings.api_url,
        settings.api_token,
        connect_timeout=settings.connect_timeout,
        read_timeout=settings.read_timeout,
        verify_ssl=settings.verify_ssl,
    )
    create_server(client).run(transport="stdio")


if __name__ == "__main__":
    main()