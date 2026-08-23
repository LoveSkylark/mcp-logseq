"""DB tag tool handlers."""
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

class GetTagToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("get_tag")
    def get_tool_description(self):
        return Tool(name=self.name, description="Get a DB graph tag/class by name or UUID.", inputSchema={
            "type": "object", "properties": {"tag": {"type": "string"}},
            "required": ["tag"],
        })
    def _call(self, api, args): return api.get_tag(args["tag"])
    def run_tool(self, args):
        if "tag" not in args: raise RuntimeError("tag argument required")
        return self._execute(args)


class GetTagObjectsToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("get_tag_objects")
    def get_tool_description(self):
        return Tool(name=self.name, description="List DB nodes carrying a tag/class.", inputSchema={
            "type": "object", "properties": {"tag": {"type": "string"}},
            "required": ["tag"],
        })
    def _call(self, api, args): return api.get_tag_objects(args["tag"])
    def run_tool(self, args):
        if "tag" not in args: raise RuntimeError("tag argument required")
        return self._execute(args)


class GetTagsByNameToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("get_tags_by_name")
    def get_tool_description(self):
        return Tool(name=self.name, description="Find DB graph tags by name.", inputSchema={
            "type": "object", "properties": {"tag_name": {"type": "string"}},
            "required": ["tag_name"],
        })
    def _call(self, api, args): return api.get_tags_by_name(args["tag_name"])
    def run_tool(self, args):
        if "tag_name" not in args: raise RuntimeError("tag_name argument required")
        return self._execute(args)

class CreateTagToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("create_tag")
    def get_tool_description(self):
        return Tool(name=self.name, description=(
            "Create a DB graph tag/class. Prefer upsert_nodes with entityType='tag' when "
            "batching a tag alongside pages/blocks that reference it — this per-call path is "
            "fine standalone but is a separate write from upsert_nodes's batch."
        ), inputSchema={
            "type": "object", "properties": {"tag_name": {"type": "string"}, "options": {"type": "object"}},
            "required": ["tag_name"],
        })
    def _call(self, api, args): return api.create_tag(args["tag_name"], args.get("options"))
    def run_tool(self, args):
        if "tag_name" not in args: raise RuntimeError("tag_name argument required")
        return self._execute(args)


class AddBlockTagToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("add_block_tag")
    def get_tool_description(self):
        return Tool(name=self.name, description="Add a tag/class to a DB node.", inputSchema={
            "type": "object", "properties": {"block_uuid": {"type": "string"}, "tag": {"type": "string"}},
            "required": ["block_uuid", "tag"],
        })
    def _call(self, api, args):
        return api.add_block_tag(args["block_uuid"], args["tag"])
    def _access_check(self, api, args):
        _enforce_block_namespace_access(api, args["block_uuid"])
        _enforce_block_tag_access(api, args["block_uuid"])
    def run_tool(self, args):
        for key in ("block_uuid", "tag"):
            if key not in args: raise RuntimeError(f"{key} argument required")
        return self._execute(args)


class RemoveBlockTagToolHandler(AddBlockTagToolHandler):
    def __init__(self): super().__init__(); self.name = "remove_block_tag"
    def get_tool_description(self):
        return Tool(name=self.name, description="Remove a tag/class from a DB node.", inputSchema={
            "type": "object", "properties": {"block_uuid": {"type": "string"}, "tag": {"type": "string"}},
            "required": ["block_uuid", "tag"],
        })
    def _call(self, api, args):
        return api.remove_block_tag(args["block_uuid"], args["tag"])


class _TagRelationHandler(_DBToolHandler):
    method_name = ""

    def get_tool_description(self):
        return Tool(name=self.name, description=f"Update a DB tag relationship.", inputSchema={
            "type": "object", "properties": {
                "tag_id": {"type": "string"}, "value": {"type": "string"},
            }, "required": ["tag_id", "value"],
        })

    def _call(self, api, args):
        return getattr(api, self.method_name)(args["tag_id"], args["value"])

    def run_tool(self, args):
        for key in ("tag_id", "value"):
            if key not in args: raise RuntimeError(f"{key} argument required")
        return self._execute(args)


class AddTagPropertyToolHandler(_TagRelationHandler):
    method_name = "add_tag_property"
    def __init__(self): super().__init__("add_tag_property")


class RemoveTagPropertyToolHandler(_TagRelationHandler):
    method_name = "remove_tag_property"
    def __init__(self): super().__init__("remove_tag_property")


class AddTagExtendsToolHandler(_TagRelationHandler):
    method_name = "add_tag_extends"
    def __init__(self): super().__init__("add_tag_extends")


class RemoveTagExtendsToolHandler(_TagRelationHandler):
    method_name = "remove_tag_extends"
    def __init__(self): super().__init__("remove_tag_extends")


