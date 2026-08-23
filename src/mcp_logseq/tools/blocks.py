"""Block-level tool handlers."""
import json
from mcp.types import Tool, TextContent
from . import (
    AccessDenied,
    ToolHandler,
    _normalize_db_block,
    _enforce_namespace_access,
    _enforce_block_namespace_access,
    _enforce_page_tag_access,
    _enforce_block_tag_access,
    logger,
)
import mcp_logseq.tools as _tools

from .pages import GetPageContentToolHandler

class DeleteBlockToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("delete_block")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Delete a block from LogSeq by its UUID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "block_uuid": {
                        "type": "string",
                        "description": "UUID of the block to delete"
                    }
                },
                "required": ["block_uuid"]
            }
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if "block_uuid" not in args:
            raise RuntimeError("block_uuid argument required")

        block_uuid = args["block_uuid"]

        try:
            api = _tools._make_api()
            _enforce_block_namespace_access(api, block_uuid)
            _enforce_block_tag_access(api, block_uuid)
            api.delete_block(block_uuid)

            return [TextContent(
                type="text",
                text=f"✅ Successfully deleted block '{block_uuid}'"
            )]
        except AccessDenied:
            raise
        except ValueError as e:
            return [TextContent(
                type="text",
                text=f"❌ Error: {str(e)}"
            )]
        except Exception as e:
            logger.error(f"Failed to delete block: {str(e)}")
            return [TextContent(
                type="text",
                text=f"❌ Failed to delete block '{block_uuid}': {str(e)}"
            )]


class UpdateBlockToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("update_block")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Update the content of an existing LogSeq block by UUID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "block_uuid": {
                        "type": "string",
                        "description": "UUID of the block to update"
                    },
                    "content": {
                        "type": "string",
                        "description": "New content that replaces the block text"
                    }
                },
                "required": ["block_uuid", "content"]
            }
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if "block_uuid" not in args or "content" not in args:
            raise RuntimeError("block_uuid and content arguments required")

        block_uuid = args["block_uuid"]
        content = args["content"]

        try:
            api = _tools._make_api()
            _enforce_block_namespace_access(api, block_uuid)
            _enforce_block_tag_access(api, block_uuid)
            api.update_block(block_uuid, content)

            return [TextContent(
                type="text",
                text=f"✅ Successfully updated block '{block_uuid}'"
            )]
        except AccessDenied:
            raise
        except ValueError as e:
            return [TextContent(
                type="text",
                text=f"❌ Error: {str(e)}"
            )]
        except Exception as e:
            logger.error(f"Failed to update block: {str(e)}")
            return [TextContent(
                type="text",
                text=f"❌ Failed to update block '{block_uuid}': {str(e)}"
            )]


class GetBlockToolHandler(ToolHandler):
    """Retrieve a single block by UUID, including its content, properties, and children."""

    def __init__(self):
        super().__init__("get_block")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Get a single block by its UUID. Returns the block content, properties, and child blocks (recursively). Useful for inspecting a specific block after finding its UUID via search or query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "block_uuid": {
                        "type": "string",
                        "description": "UUID of the block to retrieve",
                    },
                    "page_name": {
                        "type": "string",
                        "description": "Optional owning page name or UUID. Not required -- get_block reads the block directly in both graph modes. If supplied, reads via get_page_data instead, which only sees the page's DIRECT children (a Logseq API limit); prefer omitting this.",
                    },
                    "include_children": {
                        "type": "boolean",
                        "description": "Whether to include child blocks recursively (default: true). DB graphs always include children because Logseq 2.0.1 hangs when false.",
                        "default": True,
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format (text or json)",
                        "enum": ["text", "json"],
                        "default": "text",
                    },
                },
                "required": ["block_uuid"],
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if "block_uuid" not in args:
            raise RuntimeError("block_uuid argument required")

        block_uuid = args["block_uuid"]
        page_name = args.get("page_name")
        include_children = args.get("include_children", True)
        output_format = args.get("format", "text")

        try:
            api = _tools._make_api()
            if _tools._get_db_mode() and page_name:
                # Direct get_block works in DB mode too (verified 2026-08-23),
                # but only sees the page's direct children when read this way;
                # kept for callers that already pass page_name.
                _enforce_namespace_access(page_name)
                _enforce_page_tag_access(api, page_name)
                result = _normalize_db_block(
                    api.get_block_from_page_data(page_name, block_uuid)
                )
            else:
                _enforce_block_namespace_access(api, block_uuid)
                _enforce_block_tag_access(api, block_uuid)
                result = api.get_block(block_uuid, include_children=include_children)

            if output_format == "json":
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            # Format as readable text using the same tree formatter as get_page_content
            content_parts = []

            # Fetch DB-mode class properties when enabled
            db_properties = {}
            if _tools._get_db_mode():
                try:
                    db_properties = api.get_blocks_db_properties([result])
                    logger.info(f"DB-mode properties found for {len(db_properties)} blocks")
                except Exception as e:
                    logger.warning(f"Could not fetch DB-mode properties: {e}")

            block_lines = GetPageContentToolHandler._format_block_tree(
                result, 0, -1, db_properties
            )
            content_parts.extend(block_lines)

            if not content_parts:
                return [TextContent(
                    type="text",
                    text=f"Block '{block_uuid}' exists but has no content.",
                )]

            return [TextContent(type="text", text="\n".join(content_parts))]

        except AccessDenied:
            raise
        except ValueError as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]
        except Exception as e:
            logger.error(f"Failed to get block: {str(e)}")
            return [TextContent(
                type="text",
                text=f"Failed to get block '{block_uuid}': {str(e)}",
            )]


class InsertNestedBlockToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("insert_nested_block")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="""Insert a new block as a child or sibling of an existing block, enabling nested hierarchical structures""",
            inputSchema={
                "type": "object",
                "properties": {
                    "parent_block_uuid": {
                        "type": "string",
                        "description": "UUID of the reference block. If sibling=false, new block becomes a CHILD of this UUID. If sibling=true, new block becomes a SIBLING of this UUID (at the same level)."
                    },
                    "content": {
                        "type": "string",
                        "description": "Content text for the new block"
                    },
                    "properties": {
                        "type": "object",
                        "description": "Optional file-graph block properties. In DB mode, do not pass bare names such as marker or priority; use upsert_nodes for supported DB data.",
                        "additionalProperties": True
                    },
                    "sibling": {
                        "type": "boolean",
                        "description": "false (default) = insert as CHILD under parent_block_uuid. true = insert as SIBLING after parent_block_uuid at the same level. For multiple children under same parent, ALWAYS use false with the parent's UUID.",
                        "default": False
                    }
                },
                "required": ["parent_block_uuid", "content"]
            }
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        """Insert a nested block under an existing block."""
        if "parent_block_uuid" not in args or "content" not in args:
            raise RuntimeError("parent_block_uuid and content arguments required")

        parent_uuid = args["parent_block_uuid"]
        content = args["content"]
        properties = args.get("properties")
        sibling = args.get("sibling", False)

        if properties and _tools._get_db_mode():
            return [TextContent(
                type="text",
                text="❌ DB graphs don't support insert_nested_block's properties "
                "argument (it's file-graph Markdown syntax and silently mints junk "
                "properties instead of a real one). Insert the block first, then use "
                "upsert_block_property or set_block_properties to set DB properties.",
            )]

        try:
            api = _tools._make_api()
            _enforce_block_namespace_access(api, parent_uuid)
            _enforce_block_tag_access(api, parent_uuid)
            result = api.insert_block_as_child(
                parent_block_uuid=parent_uuid,
                content=content,
                properties=properties,
                sibling=sibling
            )

            relationship = "sibling" if sibling else "child"
            success_msg = f"✅ Successfully inserted block as {relationship}"

            # Add block details if available
            if result and isinstance(result, dict):
                if result.get("uuid"):
                    success_msg += f"\n🆔 New block UUID: {result.get('uuid')}"
                if result.get("content"):
                    content_preview = result.get('content')
                    if len(content_preview) > 100:
                        content_preview = content_preview[:100] + "..."
                    success_msg += f"\n📝 Content: {content_preview}"

            success_msg += f"\n🔗 Inserted under parent: {parent_uuid}"

            return [TextContent(
                type="text",
                text=success_msg
            )]

        except AccessDenied:
            raise
        except ValueError as e:
            return [TextContent(
                type="text",
                text=f"❌ Error: {str(e)}"
            )]
        except Exception as e:
            logger.error(f"Failed to insert nested block: {str(e)}")
            return [TextContent(
                type="text",
                text=f"❌ Failed to insert nested block: {str(e)}"
            )]


