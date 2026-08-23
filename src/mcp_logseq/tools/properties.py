"""DB property tool handlers."""
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

class GetPropertyToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("get_property")
    def get_tool_description(self):
        return Tool(name=self.name, description="Get a typed DB graph property definition.", inputSchema={
            "type": "object", "properties": {"property_name": {"type": "string"}},
            "required": ["property_name"],
        })
    def _call(self, api, args): return api.get_property(args["property_name"])
    def run_tool(self, args):
        if "property_name" not in args: raise RuntimeError("property_name argument required")
        return self._execute(args)


class UpsertPropertyToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("upsert_property")
    def get_tool_description(self):
        return Tool(name=self.name, description=(
            "Update an EXISTING typed DB graph property (pass its full ident, e.g. "
            "':logseq.property/status'). Do not use this to CREATE a new property from a "
            "bare display name: Logseq mints it under a generic ':plugin.property._test_plugin/*' "
            "ident instead (confirmed live). Use upsert_nodes with entityType='property' to "
            "create a new property cleanly."
        ), inputSchema={
            "type": "object", "properties": {
                "property_name": {"type": "string"}, "schema": {"type": "object"},
                "options": {"type": "object"},
            }, "required": ["property_name"],
        })
    def _call(self, api, args): return api.upsert_property(args["property_name"], args.get("schema"), args.get("options"))
    def run_tool(self, args):
        if "property_name" not in args: raise RuntimeError("property_name argument required")
        return self._execute(args)


class RemovePropertyToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("remove_property")
    def get_tool_description(self):
        return Tool(name=self.name, description="Remove a DB graph property definition.", inputSchema={
            "type": "object", "properties": {"property_name": {"type": "string"}},
            "required": ["property_name"],
        })
    def _call(self, api, args): return api.remove_property(args["property_name"])
    def run_tool(self, args):
        if "property_name" not in args: raise RuntimeError("property_name argument required")
        return self._execute(args)


class GetBlockPropertiesToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("get_block_properties")

    def get_tool_description(self):
        return Tool(name=self.name, description="Get all typed properties on a DB node.", inputSchema={
            "type": "object", "properties": {
                "block_uuid": {"type": "string"},
                "page_name": {
                    "type": "string",
                    "description": "Owning page name or UUID. REQUIRED in DB mode: get_block_properties has "
                    "no working DB route, so DB reads go through get_page_data + datascript instead.",
                },
            },
            "required": ["block_uuid"],
        })

    def run_tool(self, args: dict) -> list[TextContent]:
        if "block_uuid" not in args:
            raise RuntimeError("block_uuid argument required")
        if not _tools._get_db_mode():
            return [TextContent(
                type="text",
                text="get_block_properties is available only for Logseq 2.x DB graphs. "
                "Set LOGSEQ_DB_MODE=true.",
            )]

        block_uuid = args["block_uuid"]
        page_name = args.get("page_name")
        try:
            api = _tools._make_api()
            if page_name:
                # get_block_properties has no working DB route (its cli.* candidate
                # hangs); read via get_page_data + datascript properties instead.
                _enforce_namespace_access(page_name)
                _enforce_page_tag_access(api, page_name)
                block = api.get_block_from_page_data(page_name, block_uuid)
                db_properties = api.get_blocks_db_properties([block])
                result = db_properties.get(block_uuid, {})
            else:
                _enforce_block_namespace_access(api, block_uuid)
                _enforce_block_tag_access(api, block_uuid)
                result = api.get_block_properties(block_uuid)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except AccessDenied:
            raise
        except Exception as e:
            return [TextContent(type="text", text=f"get_block_properties failed: {str(e)}")]


class GetBlockPropertyToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("get_block_property")

    def get_tool_description(self):
        return Tool(name=self.name, description="Get one typed property from a DB node.", inputSchema={
            "type": "object", "properties": {
                "block_uuid": {"type": "string"}, "property_name": {"type": "string"},
                "page_name": {
                    "type": "string",
                    "description": "Owning page name or UUID. REQUIRED in DB mode: get_block_property has "
                    "no working DB route, so DB reads go through get_page_data + datascript instead.",
                },
            }, "required": ["block_uuid", "property_name"],
        })

    def run_tool(self, args: dict) -> list[TextContent]:
        for key in ("block_uuid", "property_name"):
            if key not in args:
                raise RuntimeError(f"{key} argument required")
        if not _tools._get_db_mode():
            return [TextContent(
                type="text",
                text="get_block_property is available only for Logseq 2.x DB graphs. "
                "Set LOGSEQ_DB_MODE=true.",
            )]

        block_uuid = args["block_uuid"]
        property_name = args["property_name"]
        page_name = args.get("page_name")
        try:
            api = _tools._make_api()
            if page_name:
                # get_block_property has no working DB route (its cli.* candidate
                # hangs); read via get_page_data + datascript properties instead.
                _enforce_namespace_access(page_name)
                _enforce_page_tag_access(api, page_name)
                block = api.get_block_from_page_data(page_name, block_uuid)
                db_properties = api.get_blocks_db_properties([block])
                result = db_properties.get(block_uuid, {}).get(property_name)
            else:
                _enforce_block_namespace_access(api, block_uuid)
                _enforce_block_tag_access(api, block_uuid)
                result = api.get_block_property(block_uuid, property_name)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except AccessDenied:
            raise
        except Exception as e:
            return [TextContent(type="text", text=f"get_block_property failed: {str(e)}")]


class UpsertBlockPropertyToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("upsert_block_property")
    def get_tool_description(self):
        return Tool(name=self.name, description=(
            "Set an EXISTING typed property on a DB node. property_name must be the property's "
            "full ident (e.g. ':logseq.property/status'), not a bare display name — a bare name "
            "that doesn't resolve mints a junk ':plugin.property._test_plugin/*' property instead "
            "(confirmed live) rather than erroring."
        ), inputSchema={
            "type": "object", "properties": {
                "block_uuid": {"type": "string"}, "property_name": {"type": "string"},
                "value": {}, "options": {"type": "object"},
            }, "required": ["block_uuid", "property_name", "value"],
        })
    def _call(self, api, args):
        return api.upsert_block_property(args["block_uuid"], args["property_name"], args["value"], args.get("options"))
    def _access_check(self, api, args):
        _enforce_block_namespace_access(api, args["block_uuid"])
        _enforce_block_tag_access(api, args["block_uuid"])
    def run_tool(self, args):
        for key in ("block_uuid", "property_name", "value"):
            if key not in args: raise RuntimeError(f"{key} argument required")
        return self._execute(args)


class RemoveBlockPropertyToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("remove_block_property")
    def get_tool_description(self):
        return Tool(name=self.name, description="Remove a typed property from a DB node.", inputSchema={
            "type": "object", "properties": {
                "block_uuid": {"type": "string"}, "property_name": {"type": "string"},
            }, "required": ["block_uuid", "property_name"],
        })
    def _call(self, api, args):
        return api.remove_block_property(args["block_uuid"], args["property_name"])
    def _access_check(self, api, args):
        _enforce_block_namespace_access(api, args["block_uuid"])
        _enforce_block_tag_access(api, args["block_uuid"])
    def run_tool(self, args):
        for key in ("block_uuid", "property_name"):
            if key not in args: raise RuntimeError(f"{key} argument required")
        return self._execute(args)


