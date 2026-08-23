"""DB-native (logseq.cli.*) tool handlers."""
import json
import uuid
from mcp.types import Tool, TextContent
from .. import access, logseq, parser
from . import (
    AccessDenied,
    ToolHandler,
    _DBToolHandler,
    _UUID_REF_PATTERN,
    _collect_block_uuids,
    _resolve_block_refs,
    _extract_tags,
    _is_page_excluded,
    _namespace_matches,
    _is_namespace_blocked,
    _is_page_blocked,
    _db_entity_name,
    _db_entity_tags,
    _enforce_db_entity_access,
    _normalize_db_block,
    _normalize_db_page_data,
    _validate_upsert_operations,
    _enforce_namespace_access,
    _enforce_block_namespace_access,
    _enforce_page_tag_access,
    _enforce_block_tag_access,
    logger,
)
import mcp_logseq.tools as _tools

class SetBlockPropertiesToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("set_block_properties")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Set properties on a block in Logseq DB mode. Prefer full property idents such as ':logseq.property/status'; display names are resolved case-insensitively when unambiguous.",
            inputSchema={
                "type": "object",
                "properties": {
                    "block_uuid": {
                        "type": "string",
                        "description": "UUID of the block to update",
                    },
                    "properties": {
                        "type": "object",
                        "description": "Properties to set as {ident-or-name: value} pairs. Prefer full idents (e.g. ':logseq.property/status': 'Doing').",
                        "additionalProperties": True,
                    },
                },
                "required": ["block_uuid", "properties"],
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        """Set DB-mode properties on a block."""
        if not _tools._get_db_mode():
            return [TextContent(
                type="text",
                text="❌ set_block_properties requires LOGSEQ_DB_MODE=true (only works with Logseq DB-mode graphs)",
            )]

        if "block_uuid" not in args:
            raise RuntimeError("block_uuid argument required")

        # Access control is enforced even though the operation itself is
        # refused below, so a restricted block never gets a different
        # response shape than an allowed one would.
        api = _tools._make_api()
        _enforce_block_namespace_access(api, args["block_uuid"])
        _enforce_block_tag_access(api, args["block_uuid"])

        return [TextContent(
            type="text",
            text="❌ Graph DB does not use set_block_properties (it calls the same "
            "logseq.Editor.upsertBlockProperty confirmed to hang indefinitely on live "
            "Logseq 2.0.1 DB graphs). Set properties at block-creation time via "
            "upsert_nodes instead.",
        )]


class UpsertNodesToolHandler(ToolHandler):
    """
    Batch create/edit nodes in one call via Logseq's CLI API.

    Uses `logseq.cli.upsertNodes`, a different write path from Editor.*:
    many edits travel in a single HTTP request, so the per-call write
    ceiling that wedges Editor writes does not apply. Verified at ~1.5s
    for a batch, with dry-run validation available.
    """

    def __init__(self):
        super().__init__("upsert_nodes")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description=(
                "Batch create or edit many blocks/pages in ONE call. Strongly preferred "
                "over repeated update_block/insert_nested_block: Editor writes wedge the "
                "server after ~7 calls, this does not. Commits validate with a dry run by "
                "default; set dry_run=true to validate without committing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "operations": {
                        "type": "array",
                        "description": (
                            "List of operations. Each: {operation: 'add'|'edit', "
                            "entityType: 'block'|'page'|'tag'|'property', "
                            "id: '<uuid>' (required for edit, and its data must also include "
                            "title), data: {title: '<content>', page-id: '<uuid>' (add block "
                            "only), tags: ['<tag-uuid>', ...]}}. No parent/parent-id key "
                            "exists for block hierarchy — use insert_nested_block to nest a "
                            "block under another. Link by UUID — [[<page-uuid>]] — never by "
                            "page name."
                        ),
                        "items": {"type": "object"},
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Validate only, do not commit. Default false.",
                        "default": False,
                    },
                    "validate_before_commit": {
                        "type": "boolean",
                        "description": "Run Logseq's dry-run validation before a commit. Default true.",
                        "default": True,
                    },
                },
                "required": ["operations"],
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if "operations" not in args:
            raise RuntimeError("operations argument required")

        if not _tools._get_db_mode():
            return [TextContent(
                type="text",
                text="upsert_nodes is available only for Logseq 2.x DB graphs. "
                "Set LOGSEQ_DB_MODE=true.",
            )]

        operations = args["operations"]
        dry_run = bool(args.get("dry_run", False))
        validate_before_commit = bool(args.get("validate_before_commit", True))

        if not isinstance(operations, list) or not operations:
            return [TextContent(type="text", text="Error: operations must be a non-empty list")]

        try:
            _validate_upsert_operations(operations)
            api = _tools._make_api()
            acl = access.get_access_config()
            if acl.include_namespaces or acl.exclude_namespaces or acl.exclude_tags:
                for operation in operations:
                    if not isinstance(operation, dict):
                        raise RuntimeError("each operation must be an object")
                    data = operation.get("data") or {}
                    entity_type = operation.get("entityType")
                    if entity_type == "page" and operation.get("operation") == "add":
                        _enforce_namespace_access(str(data.get("title", "")))
                    elif entity_type == "block":
                        block_uuid = operation.get("id")
                        page_uuid = data.get("page-id")
                        target_uuid = block_uuid or page_uuid
                        if target_uuid:
                            page_name = api.get_block_page_name(str(target_uuid))
                            if page_name:
                                _enforce_namespace_access(page_name)
                            elif page_uuid:
                                page_data = api.get_page_data(str(page_uuid))
                                entity = page_data.get("entity", {}) if isinstance(page_data, dict) else {}
                                _enforce_db_entity_access(entity, str(page_uuid))
                            else:
                                raise AccessDenied(
                                    f"Access denied: cannot verify block '{target_uuid}'."
                                )
            if dry_run:
                result = api.upsert_nodes(operations, dry_run=True)
                label = "DRY RUN (nothing committed)"
            else:
                validation_result = None
                if validate_before_commit:
                    validation_result = api.upsert_nodes(operations, dry_run=True)
                result = api.upsert_nodes(operations, dry_run=False)
                label = "VALIDATED AND COMMITTED" if validation_result is not None else "COMMITTED"
                if validation_result is not None:
                    result = f"Validation: {validation_result}\nCommit: {result}"
            return [TextContent(
                type="text",
                text=f"{label} — {len(operations)} operation(s)\n{result}"
            )]
        except AccessDenied:
            raise
        except Exception as e:
            logger.error(f"upsert_nodes failed: {str(e)}")
            return [TextContent(type="text", text=f"Failed to upsert nodes: {str(e)}")]


class GetPageDataToolHandler(ToolHandler):
    """Read a whole page via the CLI API (Editor.getPageBlocksTree hangs in 2.0.1)."""

    def __init__(self):
        super().__init__("get_page_data")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description=(
                "Read a full page and its block tree via logseq.cli.getPageData. "
                "Use this instead of get_page_content, which hangs in Logseq 2.0.1."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "page_name": {
                        "type": "string",
                        "description": "Page name or UUID",
                    }
                },
                "required": ["page_name"],
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if "page_name" not in args:
            raise RuntimeError("page_name argument required")

        if not _tools._get_db_mode():
            return [TextContent(
                type="text",
                text="get_page_data is available only for Logseq 2.x DB graphs. "
                "Set LOGSEQ_DB_MODE=true.",
            )]

        try:
            api = _tools._make_api()
            result = api.get_page_data(args["page_name"])
            if isinstance(result, dict):
                entity = result.get("entity") or result.get("page") or {}
                if isinstance(entity, dict):
                    _enforce_db_entity_access(entity, args["page_name"])
            return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
        except Exception as e:
            logger.error(f"get_page_data failed: {str(e)}")
            return [TextContent(type="text", text=f"Failed to get page data: {str(e)}")]


class ListTagsToolHandler(ToolHandler):
    """List tags from a Logseq 2.x DB graph."""

    def __init__(self):
        super().__init__("list_tags")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="List tags in a Logseq 2.x DB graph.",
            inputSchema={
                "type": "object",
                "properties": {
                    "expand": {
                        "type": "boolean",
                        "description": "Include idents and tag-extends metadata. Defaults to true — it's the only way to see idents/extends.",
                        "default": True,
                    },
                },
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if not _tools._get_db_mode():
            return [TextContent(
                type="text",
                text="list_tags is available only for Logseq 2.x DB graphs. "
                "Set LOGSEQ_DB_MODE=true.",
            )]
        try:
            result = _tools._make_api().list_tags(expand=bool(args.get("expand", True)))
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=f"Failed to list tags: {str(e)}")]


class ListPropertiesToolHandler(ToolHandler):
    """List properties from a Logseq 2.x DB graph."""

    def __init__(self):
        super().__init__("list_properties")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="List properties in a Logseq 2.x DB graph.",
            inputSchema={
                "type": "object",
                "properties": {
                    "expand": {
                        "type": "boolean",
                        "description": "Include idents and schema metadata. Defaults to true — it's the only way to see idents.",
                        "default": True,
                    },
                },
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if not _tools._get_db_mode():
            return [TextContent(
                type="text",
                text="list_properties is available only for Logseq 2.x DB graphs. "
                "Set LOGSEQ_DB_MODE=true.",
            )]
        try:
            result = _tools._make_api().list_properties(expand=bool(args.get("expand", True)))
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=f"Failed to list properties: {str(e)}")]


class SearchBlocksToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("search_blocks")
    def get_tool_description(self):
        return Tool(name=self.name, description="Search DB graph blocks by content.", inputSchema={
            "type": "object", "properties": {"query": {"type": "string"}},
            "required": ["query"],
        })
    def _call(self, api, args):
        if not args.get("query", "").strip(): raise RuntimeError("query is required")
        return api.search_content(args["query"], {"enable-snippet?": False})
    def run_tool(self, args): return self._execute(args)


