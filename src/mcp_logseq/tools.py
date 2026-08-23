import json
import os
import re
import logging
import threading
import uuid
from typing import Any
from urllib.parse import urlparse
from . import logseq
from . import parser
from . import access
from .settings import load_settings
from mcp.types import Tool, TextContent

logger = logging.getLogger("mcp-logseq")

_api_client_lock = threading.Lock()
_api_client = None
_api_client_key: tuple | None = None
_api_client_factory = None


def _get_db_mode() -> bool:
    """Return DB mode through the compatibility hook used by handlers/tests."""
    setting = _get_db_mode_setting()
    if setting is True:
        return True
    if setting == "auto":
        if _api_client is None:
            _make_api()
        return _api_client is not None and _api_client.db_mode is True
    return False


def _get_db_mode_setting() -> bool | str:
    return load_settings().db_mode


def _make_api() -> logseq.LogSeq:
    global _api_client, _api_client_key, _api_client_factory

    settings = load_settings()
    protocol = settings.protocol
    host = settings.host
    port = settings.port
    timeout = settings.timeout
    key = (
        settings.api_key,
        protocol,
        host,
        port,
        settings.verify_ssl,
        timeout,
        settings.db_mode,
    )
    with _api_client_lock:
        if key != _api_client_key or logseq.LogSeq is not _api_client_factory:
            _api_client = logseq.LogSeq(
                api_key=settings.api_key,
                protocol=protocol,
                host=host,
                port=port,
                verify_ssl=settings.verify_ssl,
                timeout=timeout,
                db_mode=settings.db_mode is True,
            )
            if settings.db_mode == "auto":
                _api_client.db_mode = _api_client.check_current_is_db_graph()
            _api_client_key = key
            _api_client_factory = logseq.LogSeq
        return _api_client


# Regex matching [[uuid]] references in DB-mode block content
_UUID_REF_PATTERN = re.compile(r"\[\[([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]\]")


def _collect_block_uuids(blocks: list[dict]) -> set[str]:
    """Recursively collect all page-reference UUIDs from block content strings."""
    uuids: set[str] = set()
    for block in blocks:
        content = block.get("content", "")
        uuids.update(_UUID_REF_PATTERN.findall(content))
        children = block.get("children", [])
        if children:
            uuids.update(_collect_block_uuids(children))
    return uuids


def _resolve_block_refs(content: str, uuid_map: dict[str, str]) -> str:
    """Replace [[uuid]] patterns in content with [[Page Name]] using a pre-resolved map."""
    def _replace(match: re.Match) -> str:
        uuid = match.group(1)
        name = uuid_map.get(uuid)
        if name:
            return f"[[{name}]]"
        return match.group(0)  # Keep original if not resolved

    return _UUID_REF_PATTERN.sub(_replace, content)


def _extract_tags(properties: dict) -> list[str]:
    """Extract tags from a Logseq properties dict (list or comma-string form)."""
    raw = properties.get("tags", [])
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    elif isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    return []


def _is_page_excluded(page: dict, exclude_tags: list[str]) -> bool:
    """Return True if the page has any tag in exclude_tags."""
    if not exclude_tags:
        return False
    props = page.get("properties") or {}
    return any(t in exclude_tags for t in _extract_tags(props))


AccessDenied = access.AccessDenied


def _namespace_matches(page_name: str, ns: str) -> bool:
    """Segment-based, case-insensitive namespace match.

    'work' matches 'work' and 'work/...'; it does NOT match 'workshop'.
    """
    p = page_name.lower()
    n = ns.lower().rstrip("/")
    if not n:
        return False
    return p == n or p.startswith(n + "/")


def _is_namespace_blocked(page_name: str, include: list[str], exclude: list[str]) -> bool:
    """Apply namespace rules. Exclude wins; include is a strict allow-list."""
    if any(_namespace_matches(page_name, n) for n in exclude):
        return True
    if include and not any(_namespace_matches(page_name, n) for n in include):
        return True
    return False


def _is_page_blocked(page: dict | None, page_name: str) -> bool:
    """Combined tag OR namespace block check (used for result filtering)."""
    return access.is_page_blocked(page, page_name)


def _db_entity_name(entity: dict, fallback: str) -> str:
    """Return a DB graph entity's display name across API output shapes."""
    return str(
        entity.get("block/title")
        or entity.get("block/name")
        or entity.get("title")
        or entity.get("name")
        or fallback
    )


def _db_entity_tags(entity: dict) -> list[str]:
    """Extract DB graph tag names from normalized or namespaced entity data."""
    raw_tags = entity.get("block/tags", entity.get("tags", [])) or []
    tags: list[str] = []
    for tag in raw_tags if isinstance(raw_tags, list) else [raw_tags]:
        if isinstance(tag, dict):
            value = tag.get("block/title") or tag.get("block/name") or tag.get("title")
        else:
            value = tag
        if value:
            tags.append(str(value))
    return tags


def _enforce_db_entity_access(entity: dict, fallback_name: str) -> None:
    """Apply namespace and tag ACLs to a DB graph page/entity response."""
    page_name = _db_entity_name(entity, fallback_name)
    acl = access.get_access_config()
    if (
        access.is_page_blocked(entity, page_name)
        or any(tag in acl.exclude_tags for tag in _db_entity_tags(entity))
    ):
        raise AccessDenied(
            f"Access denied: page '{page_name}' is restricted "
            "and cannot be accessed by this assistant."
        )


def _normalize_db_block(block: dict) -> dict:
    """Add the legacy aliases used by the text formatter to DB API blocks."""
    normalized = dict(block)
    normalized["content"] = str(
        block.get("block/title") or block.get("content") or ""
    )
    if "uuid" not in normalized and "block/uuid" in block:
        normalized["uuid"] = str(block["block/uuid"])
    children = block.get("block/children", block.get("children", [])) or []
    normalized["children"] = [
        _normalize_db_block(child) for child in children if isinstance(child, dict)
    ]
    normalized.setdefault("properties", block.get("properties", {}))
    return normalized


def _normalize_db_page_data(result: dict, fallback_name: str) -> dict:
    """Normalize Logseq 2.x page-data output for existing MCP responses."""
    entity = result.get("entity") or result.get("page") or {}
    blocks = result.get("blocks", []) or []
    page = dict(entity) if isinstance(entity, dict) else {}
    page.setdefault("name", _db_entity_name(page, fallback_name))
    page.setdefault("originalName", page["name"])
    return {
        "page": page,
        "blocks": [
            _normalize_db_block(block) for block in blocks if isinstance(block, dict)
        ],
    }


def _validate_upsert_operations(operations: list[dict]) -> None:
    """Validate the public subset of Logseq 2.x upsertNodes operations."""
    allowed_operations = {"add", "edit"}
    allowed_entities = {"block", "page", "tag", "property"}
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ValueError(f"operation {index} must be an object")
        operation_type = operation.get("operation")
        entity_type = operation.get("entityType")
        data = operation.get("data")
        if operation_type not in allowed_operations:
            raise ValueError(f"operation {index} has invalid operation")
        if entity_type not in allowed_entities:
            raise ValueError(f"operation {index} has invalid entityType")
        if not isinstance(data, dict):
            raise ValueError(f"operation {index} data must be an object")
        if operation_type == "edit":
            operation_id = operation.get("id")
            if not isinstance(operation_id, str):
                raise ValueError(f"operation {index} edit requires a string id")
            try:
                uuid.UUID(operation_id)
            except ValueError as error:
                raise ValueError(f"operation {index} edit id must be a UUID") from error
        if operation_type == "add" and entity_type == "block":
            if not isinstance(data.get("title"), str) or not data["title"].strip():
                raise ValueError(f"operation {index} block add requires title")
            if not isinstance(data.get("page-id"), str) or not data["page-id"].strip():
                raise ValueError(f"operation {index} block add requires page-id")
        if operation_type == "add" and entity_type in {"page", "tag", "property"}:
            if not isinstance(data.get("title"), str) or not data["title"].strip():
                raise ValueError(f"operation {index} add requires title")
        if "tags" in data and (
            not isinstance(data["tags"], list)
            or any(not isinstance(tag, str) for tag in data["tags"])
        ):
            raise ValueError(f"operation {index} tags must be a string array")
        if "tags" in data:
            for tag in data["tags"]:
                try:
                    uuid.UUID(tag)
                except ValueError as error:
                    raise ValueError(
                        f"operation {index} tags must contain UUID strings"
                    ) from error


def _enforce_namespace_access(page_name: str) -> None:
    """Raise AccessDenied if page_name is blocked by namespace rules.

    Name-based only (no tag check — that needs fetched page properties).
    """
    access.enforce_namespace_access(page_name)


def _enforce_block_namespace_access(api, block_uuid: str) -> None:
    """Resolve a block's owning page and enforce namespace rules.

    Fail-closed: when namespace rules are configured but the page cannot be
    resolved, access is denied. When no namespace rules exist, this is a no-op.
    """
    access.enforce_block_namespace_access(api, block_uuid)


def _enforce_page_tag_access(api, page_name: str) -> None:
    """Raise AccessDenied if an EXISTING page carries an excluded tag.

    Complements the name-based namespace check on write handlers: namespace
    rules can be evaluated from the name alone, but tag exclusion requires the
    page's properties, so this fetches the page. A no-op when no exclude tags
    are configured.

    Two cases are NOT excluded — but only the first is also a quiet pass:
    - ``get_page_content`` returns None/empty: the page does not exist (or has
      no properties) and therefore carries no tags. Treated as NOT excluded so
      ``update_page`` keeps working for brand-new pages.
    - ``get_page_content`` RAISES: with exclude tags configured we cannot verify
      the page's tags, so we must NOT silently proceed with the write. The error
      is allowed to propagate (no try/except) so the calling write handler
      aborts the mutation via its normal error path (fail-closed). It is not an
      AccessDenied, so it isn't mislabeled — it just isn't swallowed.
    """
    access.enforce_page_tag_access(api, page_name)


def _enforce_block_tag_access(api, block_uuid: str) -> None:
    """Resolve a block's owning page and enforce tag exclusion on it.

    A no-op when no exclude tags are configured. When tags ARE configured but
    the owning page cannot be resolved, access is denied (fail-closed), mirroring
    ``_enforce_block_namespace_access``.
    """
    access.enforce_block_tag_access(api, block_uuid)


class ToolHandler:
    access_policy: list = []

    def __init__(self, tool_name: str):
        self.name = tool_name

    def get_tool_description(self) -> Tool:
        raise NotImplementedError()

    def run_tool(self, args: dict) -> list[TextContent]:
        api = _make_api()
        for policy in self.access_policy:
            policy.enforce(api, args)
        return self._run(api, args)

    def _run(self, api, args: dict) -> list[TextContent]:
        raise NotImplementedError()


# =============================================================================
# TOOL HANDLERS (with proper markdown parsing and block hierarchy)
# =============================================================================


class CreatePageToolHandler(ToolHandler):
    """
    Create a new page with proper block hierarchy.

    Parses markdown content into Logseq blocks, supporting:
    - Headings (# ## ###) with nested hierarchy
    - Bullet and numbered lists with nesting
    - Code blocks (fenced with ```)
    - Blockquotes (>)
    - YAML frontmatter for page properties
    """

    def __init__(self):
        super().__init__("create_page")

    def get_tool_description(self):
        return Tool(
            name=self.name,
                        description=(
                                "Create a page from Markdown. Existing page names are rejected to make "
                                "retries safe. Headings and lists become nested blocks; YAML frontmatter "
                                "and explicit properties become page properties."
                        ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title of the new page"},
                    "content": {
                        "type": "string",
                        "description": "Markdown content to parse into blocks (optional)",
                    },
                    "properties": {
                        "type": "object",
                        "description": "Page properties (merged with frontmatter if both provided)",
                        "additionalProperties": True,
                    },
                },
                "required": ["title"],
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if "title" not in args:
            raise RuntimeError("title argument required")

        title = args["title"]
        content = args.get("content", "")
        explicit_properties = args.get("properties", {})

        _enforce_namespace_access(title)

        try:
            api = _make_api()

            # Refuse to create a duplicate: Logseq auto-numbers pages with an
            # existing name ("Page(1)", "Page 2"), which silently fragments
            # content when a timed-out create_page is retried (issue #58).
            if api.page_exists(title):
                raise ValueError(
                    f"Page '{title}' already exists. Use update_page to modify "
                    "it (mode='append' or mode='replace'), or get_page_content "
                    "to inspect it. If a previous create_page call timed out, "
                    "the page may already contain the content you sent."
                )

            # Parse the content
            parsed = (
                parser.parse_content(content) if content else parser.ParsedContent()
            )

            # Merge properties: explicit properties override frontmatter
            page_properties = {**parsed.properties, **explicit_properties}

            # Convert blocks to batch format
            blocks = parsed.to_batch_format()

            # Create the page with blocks
            api.create_page_with_blocks(title, blocks, page_properties)

            # Build success message
            block_count = len(blocks)
            prop_count = len(page_properties)

            msg_parts = [f"Successfully created page '{title}'"]
            if block_count > 0:
                msg_parts.append(f"  - {block_count} top-level block(s) created")
            if prop_count > 0:
                msg_parts.append(f"  - {prop_count} page property/ies set")

            return [TextContent(type="text", text="\n".join(msg_parts))]
        except Exception as e:
            logger.error(f"Failed to create page: {str(e)}")
            raise


class ListPagesToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("list_pages")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Lists all pages in a LogSeq graph.",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_journals": {
                        "type": "boolean",
                        "description": "Whether to include journal/daily notes in the list",
                        "default": False,
                    }
                },
                "required": [],
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        include_journals = args.get("include_journals", False)

        try:
            api = _make_api()
            result = api.list_pages()

            # Format pages for display
            pages_info = []
            for page in result:
                # Skip if it's a journal page and we don't want to include those
                is_journal = page.get("journal?", False)
                if is_journal and not include_journals:
                    continue
                # Security: pages blocked by tag OR namespace are invisible
                name_for_check = page.get("originalName") or page.get("name", "")
                if _is_page_blocked(page, name_for_check):
                    continue

                # Get page information
                name = page.get("originalName") or page.get("name", "<unknown>")

                # Build page info string
                info_parts = [f"- {name}"]
                if is_journal:
                    info_parts.append("[journal]")

                pages_info.append(" ".join(info_parts))

            # Sort alphabetically by page name
            pages_info.sort()

            # Build response
            count_msg = f"\nTotal pages: {len(pages_info)}"
            journal_msg = (
                " (excluding journal pages)"
                if not include_journals
                else " (including journal pages)"
            )

            response = (
                "LogSeq Pages:\n\n" + "\n".join(pages_info) + count_msg + journal_msg
            )

            return [TextContent(type="text", text=response)]

        except Exception as e:
            logger.error(f"Failed to list pages: {str(e)}")
            raise


class GetPageContentToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("get_page_content")

    @staticmethod
    def _format_block_tree(
        block: dict, indent_level: int = 0, max_depth: int = -1,
        db_properties: dict[str, dict[str, str]] | None = None,
        uuid_map: dict[str, str] | None = None,
    ) -> list[str]:
        """
        Recursively format a block and its children with proper indentation.

        Args:
            block: Block dict with 'content', 'children', and optional 'properties', 'marker'
            indent_level: Current indentation level (0-based)
            max_depth: Maximum depth to recurse (-1 for unlimited)
            db_properties: DB-mode class properties keyed by block UUID
            uuid_map: Mapping of page UUIDs to page names for resolving [[uuid]] refs

        Returns:
            List of formatted lines for this block and its children
        """
        lines = []

        # Get block content
        content = block.get("content", "").strip()

        # Resolve [[uuid]] references to [[Page Name]] if a map is provided
        if uuid_map and content:
            content = _resolve_block_refs(content, uuid_map)
        if not content:
            return lines

        # Build the formatted line with indentation.
        # Skip adding "- " if the content already starts with it to avoid
        # double-wrapping blocks whose text begins with a list marker.
        indent = "  " * indent_level
        if content.startswith(("- ", "* ", "+ ")) or content in ("-", "*", "+"):
            line = f"{indent}{content}"
        else:
            line = f"{indent}- {content}"
        lines.append(line)

        # In DB-mode, properties are NOT embedded in content — render from dict
        # In Markdown-mode, properties are already in block content — skip to avoid duplicates
        if _get_db_mode():
            properties = block.get("properties", {})
            if properties:
                for key, value in properties.items():
                    if isinstance(key, str) and key.startswith(":logseq"):
                        continue
                    if f"{key}::" not in content:
                        lines.append(f"{indent}  {key}:: {value}")

            # DB-mode class properties (from datascript query)
            block_uuid = str(block.get("uuid", ""))
            if db_properties and block_uuid in db_properties:
                for key, value in db_properties[block_uuid].items():
                    lines.append(f"{indent}  {key}:: {value}")

        # Process children if we haven't hit the depth limit
        children = block.get("children", [])
        if children and (max_depth == -1 or indent_level < max_depth):
            for child in children:
                child_lines = GetPageContentToolHandler._format_block_tree(
                    child, indent_level + 1, max_depth, db_properties, uuid_map
                )
                lines.extend(child_lines)

        return lines

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Get the content of a specific page from LogSeq.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_name": {
                        "type": "string",
                        "description": "Name of the page to retrieve",
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format (text or json)",
                        "enum": ["text", "json"],
                        "default": "text",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum nesting depth to display (default: -1 for unlimited)",
                        "default": -1,
                    },
                    "resolve_refs": {
                        "type": "boolean",
                        "description": "Resolve [[uuid]] page references to [[Page Name]] in DB mode (default: true)",
                        "default": True,
                    },
                },
                "required": ["page_name"],
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        """Get and format LogSeq page content."""
        logger.info(f"Getting page content with args: {args}")

        if "page_name" not in args:
            raise RuntimeError("page_name argument required")

        # Names can be checked before any API call; UUIDs require DB resolution.
        try:
            is_uuid = uuid.UUID(str(args["page_name"]))
        except (ValueError, AttributeError, TypeError):
            is_uuid = None
        if is_uuid is None:
            _enforce_namespace_access(args["page_name"])

        try:
            api = _make_api()
            if _get_db_mode() and getattr(api, "db_mode", False) is True:
                raw_result = api.get_page_data(args["page_name"])
                if not isinstance(raw_result, dict):
                    return [TextContent(
                        type="text", text=f"Page '{args['page_name']}' not found."
                    )]
                entity = raw_result.get("entity") or raw_result.get("page") or {}
                if "entity" not in raw_result and "blocks" not in raw_result:
                    result = {
                        "page": raw_result,
                        "blocks": api.get_page_blocks(args["page_name"]),
                    }
                else:
                    if isinstance(entity, dict):
                        _enforce_db_entity_access(entity, args["page_name"])
                    result = _normalize_db_page_data(raw_result, args["page_name"])
                if isinstance(entity, dict) and result is raw_result:
                    _enforce_db_entity_access(entity, args["page_name"])
            else:
                result = api.get_page_content(args["page_name"])

            if not result:
                return [
                    TextContent(
                        type="text", text=f"Page '{args['page_name']}' not found."
                    )
                ]

            # Security: block access to restricted pages (tag OR namespace) — fail loudly
            if _is_page_blocked(result.get("page", {}), args["page_name"]):
                raise AccessDenied(
                    f"Access denied: page '{args['page_name']}' is restricted "
                    f"and cannot be accessed by this assistant."
                )

            # Handle JSON format request
            if args.get("format") == "json":
                # In DB mode with resolve_refs, enrich JSON with resolved page names
                if _get_db_mode() and args.get("resolve_refs", True):
                    blocks = result.get("blocks", [])
                    page_uuids = _collect_block_uuids(blocks)
                    if page_uuids:
                        try:
                            uuid_map = api.resolve_page_uuids(list(page_uuids))
                            if uuid_map:
                                result = dict(result)
                                result["resolved_refs"] = uuid_map
                        except Exception as e:
                            logger.warning(f"Could not resolve refs for JSON: {e}")
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            # Format as readable text
            content_parts = []

            # Get blocks from the result structure
            blocks = result.get("blocks", [])

            # Fetch DB-mode class properties (only when LOGSEQ_DB_MODE is enabled)
            db_properties = {}
            uuid_map: dict[str, str] = {}
            if _get_db_mode():
                try:
                    db_properties = api.get_blocks_db_properties(blocks)
                    logger.info(f"DB-mode properties found for {len(db_properties)} blocks")
                except Exception as e:
                    logger.warning(f"Could not fetch DB-mode properties: {e}")

                # Resolve [[uuid]] page references to readable names
                resolve_refs = args.get("resolve_refs", True)
                if resolve_refs:
                    try:
                        page_uuids = _collect_block_uuids(blocks)
                        if page_uuids:
                            uuid_map = api.resolve_page_uuids(list(page_uuids))
                    except Exception as e:
                        logger.warning(f"Could not resolve page refs: {e}")

            # Blocks content - use recursive formatter
            max_depth = args.get("max_depth", -1)
            if blocks:
                for block in blocks:
                    if isinstance(block, dict):
                        block_lines = self._format_block_tree(
                            block, 0, max_depth, db_properties, uuid_map
                        )
                        content_parts.extend(block_lines)
                    elif isinstance(block, str) and block.strip():
                        content_parts.append(f"- {block}")
            else:
                # Empty page - return single dash
                content_parts.append("-")

            return [TextContent(type="text", text="\n".join(content_parts))]

        except Exception as e:
            logger.error(f"Failed to get page content: {str(e)}")
            raise


class DeletePageToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("delete_page")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Delete a page from LogSeq.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_name": {
                        "type": "string",
                        "description": "Name of the page to delete",
                    }
                },
                "required": ["page_name"],
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if "page_name" not in args:
            raise RuntimeError("page_name argument required")

        _enforce_namespace_access(args["page_name"])

        try:
            api = _make_api()
            _enforce_page_tag_access(api, args["page_name"])
            result = api.delete_page(args["page_name"])

            # Build detailed success message
            page_name = args["page_name"]
            success_msg = f"✅ Successfully deleted page '{page_name}'"

            # Add any additional info from the API result if available
            if result and isinstance(result, dict):
                if result.get("success"):
                    success_msg += (
                        f"\n📋 Status: {result.get('message', 'Deletion confirmed')}"
                    )

            success_msg += (
                f"\n🗑️  Page '{page_name}' has been permanently removed from LogSeq"
            )

            return [TextContent(type="text", text=success_msg)]
        except AccessDenied:
            raise
        except ValueError as e:
            # Handle validation errors (page not found) gracefully
            return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
        except Exception as e:
            logger.error(f"Failed to delete page: {str(e)}")
            return [
                TextContent(
                    type="text",
                    text=f"❌ Failed to delete page '{args['page_name']}': {str(e)}",
                )
            ]


class UpdatePageToolHandler(ToolHandler):
    """
    Update a page with proper block hierarchy support.

    Supports two modes:
    - append: Add new blocks after existing content (default)
    - replace: Clear existing content and add new blocks
    """

    def __init__(self):
        super().__init__("update_page")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="""Update a page in Logseq with new content and/or properties.

Supports two modes:
- append: Add new blocks after existing content (default)
- replace: Clear all existing blocks and add new content

Markdown is parsed into proper block hierarchy just like create_page.
YAML frontmatter in content will be merged with explicit properties.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_name": {
                        "type": "string",
                        "description": "Name of the page to update",
                    },
                    "content": {
                        "type": "string",
                        "description": "Markdown content to add or replace with",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["append", "replace"],
                        "default": "append",
                        "description": "append: add after existing content. replace: clear page and add new content.",
                    },
                    "properties": {
                        "type": "object",
                        "description": "Page properties to set/update",
                        "additionalProperties": True,
                    },
                },
                "required": ["page_name"],
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if "page_name" not in args:
            raise RuntimeError("page_name argument required")

        page_name = args["page_name"]
        content = args.get("content", "")
        mode = args.get("mode", "append")
        explicit_properties = args.get("properties", {})

        _enforce_namespace_access(page_name)

        # Validate that at least one update is provided
        if not content and not explicit_properties:
            return [
                TextContent(
                    type="text",
                    text="Error: Either 'content' or 'properties' must be provided for update",
                )
            ]

        api = _make_api()
        _enforce_page_tag_access(api, page_name)

        try:
            # Parse the content
            parsed = (
                parser.parse_content(content) if content else parser.ParsedContent()
            )

            # Merge properties: explicit properties override frontmatter
            page_properties = (
                {**parsed.properties, **explicit_properties}
                if (parsed.properties or explicit_properties)
                else None
            )

            # Convert blocks to batch format
            blocks = parsed.to_batch_format()

            # Update the page
            result = api.update_page_with_blocks(
                page_name, blocks, page_properties, mode=mode
            )

            # Build success message
            updates = result.get("updates", [])
            msg_parts = [f"Successfully updated page '{page_name}'"]

            for update_type, update_value in updates:
                if update_type == "cleared":
                    msg_parts.append("  - Existing content cleared")
                elif update_type == "properties":
                    msg_parts.append(f"  - {len(update_value)} property/ies updated")
                elif update_type == "blocks_replaced":
                    msg_parts.append(f"  - {update_value} block(s) added")
                elif update_type == "blocks_appended":
                    msg_parts.append(f"  - {update_value} block(s) appended")

            msg_parts.append(f"Mode: {mode}")

            return [TextContent(type="text", text="\n".join(msg_parts))]
        except AccessDenied:
            raise
        except ValueError as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]
        except Exception as e:
            logger.error(f"Failed to update page: {str(e)}")
            return [
                TextContent(
                    type="text", text=f"Failed to update page '{page_name}': {str(e)}"
                )
            ]


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
            api = _make_api()
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
            api = _make_api()
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
                        "description": "Owning page name or UUID. In DB mode, this uses stable page data instead of the fragile getBlock API.",
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
            api = _make_api()
            if _get_db_mode() and page_name:
                _enforce_namespace_access(page_name)
                _enforce_page_tag_access(api, page_name)
                result = api.get_block_from_page_data(page_name, block_uuid)
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
            if _get_db_mode():
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


class SearchToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("search")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Search for content across LogSeq pages, blocks, and files",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query text"},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 20,
                    },
                    "include_blocks": {
                        "type": "boolean",
                        "description": "Include block content results",
                        "default": True,
                    },
                    "include_pages": {
                        "type": "boolean",
                        "description": "Include page name results",
                        "default": True,
                    },
                    "include_files": {
                        "type": "boolean",
                        "description": "Include file name results",
                        "default": False,
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format (text or json). JSON includes block UUIDs and page identifiers for deep linking.",
                        "enum": ["text", "json"],
                        "default": "text",
                    },
                },
                "required": ["query"],
            },
        )

    @staticmethod
    def _build_excluded_page_names(
        api,
        exclude_tags: list[str],
        exclude_namespaces: list[str],
        include_namespaces: list[str],
    ) -> set[str]:
        """Return lowercased names of pages blocked by tag or namespace rules.

        Makes one extra api.list_pages() call when any rule is configured.
        Fail-closed: when rules are active but the page list cannot be built,
        the error propagates so the caller aborts rather than returning an empty
        (degraded) exclusion set that would let restricted content through.
        """
        if not exclude_tags and not exclude_namespaces and not include_namespaces:
            return set()
        try:
            pages = api.list_pages()
            blocked = set()
            for page in pages:
                name = page.get("originalName") or page.get("name", "")
                if not name:
                    continue
                if _is_page_excluded(page, exclude_tags) or _is_namespace_blocked(
                    name, include_namespaces, exclude_namespaces
                ):
                    blocked.add(name.lower())
            return blocked
        except Exception:
            # Rules are active here (guarded above), so we cannot determine what
            # to exclude. Fail-closed: re-raise so the search handler returns an
            # error instead of unfiltered results.
            logger.warning(
                "Could not build blocked page names while ACL rules are active; "
                "failing closed (search will error rather than leak)."
            )
            raise

    @staticmethod
    def _filter_db_block_results(
        block_results: list[dict],
        api,
        excluded_page_names: set[str],
    ) -> list[dict]:
        """Drop DB-mode content blocks whose owning page is excluded.

        DB-mode blocks carry a 'page' field = the owning page's UUID, so the
        owning page can be resolved to a name and checked against
        ``excluded_page_names`` (which already encodes BOTH tag and namespace
        exclusions). Fail-closed: when ``excluded_page_names`` is non-empty and a
        block's owning page cannot be resolved, the block is dropped.

        A non-empty ``excluded_page_names`` is authoritative: because
        ``_build_excluded_page_names`` fails closed when rules are active, an
        empty set genuinely means no active exclusions, so this is a no-op
        (no API calls) in that case.
        """
        if not excluded_page_names:
            return block_results

        page_uuids = [
            str(b.get("page")) for b in block_results if b.get("page")
        ]
        resolved = api.resolve_page_uuids(page_uuids) if page_uuids else {}

        kept: list[dict] = []
        for block in block_results:
            page_uuid = block.get("page")
            page_name = resolved.get(str(page_uuid)) if page_uuid else None
            if page_name is None:
                # Fail-closed: owning page unresolvable while a rule is active.
                continue
            if page_name.lower() in excluded_page_names:
                continue
            kept.append(block)
        return kept

    @staticmethod
    def _format_db_mode_results(
        result: dict, limit: int,
        include_blocks: bool, include_pages: bool, include_files: bool,
        excluded_page_names: set[str] = frozenset(),
        api=None,
    ) -> list[str]:
        """Format search results from DB-mode Logseq.

        DB-mode returns a flat 'blocks' array where each item has 'content',
        'uuid', 'page' (UUID), and 'page?' (bool). Pages and blocks are
        distinguished by the 'page?' flag.
        """
        parts: list[str] = []
        blocks = result.get("blocks", [])
        truncated = False

        # Split into pages and content blocks
        page_results = [b for b in blocks if b.get("page?")]
        block_results = [b for b in blocks if not b.get("page?")]
        block_results = SearchToolHandler._filter_db_block_results(
            block_results, api, excluded_page_names
        )

        if include_pages and page_results:
            visible_pages = [
                p for p in page_results
                if (p.get("fullTitle") or p.get("title") or p.get("content", "")).lower()
                not in excluded_page_names
            ]
            if visible_pages:
                parts.append(f"## Matching Pages ({len(visible_pages)} found)")
                for page in visible_pages[:limit]:
                    name = page.get("fullTitle") or page.get("title") or page.get("content", "")
                    parts.append(f"- {name}")
                parts.append("")
                truncated = truncated or len(visible_pages) > limit

        if include_blocks and block_results:
            parts.append(f"## Content Blocks ({len(block_results)} found)")
            for i, block in enumerate(block_results[:limit]):
                content = block.get("content", "").strip()
                # Clean up full-text search highlight markers
                content = content.replace("$pfts_2lqh>$", "").replace("$<pfts_2lqh$", "")
                if content:
                    page_id = block.get("page", "")
                    uuid = block.get("uuid", "")
                    if len(content) > 150:
                        content = content[:150] + "..."
                    parts.append(f"{i + 1}. {content}")
                    parts.append(f"   uuid: {uuid}  page: {page_id}")
            parts.append("")
            truncated = truncated or len(block_results) > limit

        if include_files and result.get("files"):
            parts.append(f"## Matching Files ({len(result['files'])} found)")
            for f in result["files"][:limit]:
                parts.append(f"- {f}")
            parts.append("")
            truncated = truncated or len(result["files"]) > limit

        if result.get("hasMore?") or truncated:
            parts.append("*More results available — increase limit to see more*")

        total = len(blocks) + len(result.get("files", []))
        parts.append(f"\n**Total results found: {total}**")
        return parts

    @staticmethod
    def _format_markdown_mode_results(
        result: dict, limit: int,
        include_blocks: bool, include_pages: bool, include_files: bool,
        excluded_page_names: set[str] = frozenset(),
    ) -> list[str]:
        """Format search results from markdown-mode Logseq.

        Markdown-mode returns separate 'blocks' (with 'block/content'),
        'pages' (list of strings), 'pages-content' (with 'block/snippet'),
        and 'files' arrays.
        """
        parts: list[str] = []
        truncated = False

        if include_blocks and result.get("blocks") and not excluded_page_names:
            # Only show blocks when no exclusion is active — markdown-mode blocks
            # carry block/content but no page identifier, so we cannot verify they
            # are safe to show (same rule as the page-snippets section below)
            blocks = result["blocks"]
            parts.append(f"## Content Blocks ({len(blocks)} found)")
            for i, block in enumerate(blocks[:limit]):
                content = block.get("block/content", "").strip()
                if content:
                    if len(content) > 150:
                        content = content[:150] + "..."
                    parts.append(f"{i + 1}. {content}")
            parts.append("")
            truncated = truncated or len(blocks) > limit

        if include_pages and result.get("pages-content"):
            snippets = result["pages-content"]
            if not excluded_page_names:
                # Only show snippets when no exclusion is active — snippets carry no
                # page identifier so we cannot verify they are safe to show
                parts.append(f"## Page Snippets ({len(snippets)} found)")
                for i, snippet in enumerate(snippets[:limit]):
                    snippet_text = snippet.get("block/snippet", "").strip()
                    if snippet_text:
                        snippet_text = snippet_text.replace("$pfts_2lqh>$", "").replace(
                            "$<pfts_2lqh$", ""
                        )
                        if len(snippet_text) > 200:
                            snippet_text = snippet_text[:200] + "..."
                        parts.append(f"{i + 1}. {snippet_text}")
                parts.append("")
                truncated = truncated or len(snippets) > limit

        if include_pages and result.get("pages"):
            pages = result["pages"]
            visible_pages = [p for p in pages if p.lower() not in excluded_page_names]
            if visible_pages:
                parts.append(f"## Matching Pages ({len(visible_pages)} found)")
                for page in visible_pages[:limit]:
                    parts.append(f"- {page}")
                parts.append("")
                truncated = truncated or len(visible_pages) > limit

        if include_files and result.get("files"):
            files = result["files"]
            parts.append(f"## Matching Files ({len(files)} found)")
            for f in files[:limit]:
                parts.append(f"- {f}")
            parts.append("")
            truncated = truncated or len(files) > limit

        if result.get("has-more?") or truncated:
            parts.append("*More results available — increase limit to see more*")

        total = (
            len(result.get("blocks", []))
            + len(result.get("pages", []))
            + len(result.get("pages-content", []))
            + len(result.get("files", []))
        )
        parts.append(f"\n**Total results found: {total}**")
        return parts

    @staticmethod
    def _build_json_results(
        result: dict, query: str, limit: int,
        include_blocks: bool, include_pages: bool, include_files: bool,
        excluded_page_names: set[str] = frozenset(),
        api=None,
    ) -> dict:
        """Build structured search results with UUIDs and page identifiers.

        Applies the same exclusion filtering, include flags, and limit as the
        text formatters, but preserves the raw fields (uuid, page) so callers
        can build logseq:// deep links without follow-up calls.
        """
        out: dict = {"query": query, "mode": "db" if _get_db_mode() else "markdown"}

        if _get_db_mode():
            blocks = result.get("blocks", [])
            if include_pages:
                pages = [
                    p for p in blocks
                    if p.get("page?")
                    and (p.get("fullTitle") or p.get("title") or p.get("content", "")).lower()
                    not in excluded_page_names
                ]
                out["pages"] = pages[:limit]
            if include_blocks:
                visible_blocks = SearchToolHandler._filter_db_block_results(
                    [b for b in blocks if not b.get("page?")],
                    api, excluded_page_names,
                )
                block_results = []
                for block in visible_blocks[:limit]:
                    block = dict(block)
                    content = block.get("content", "")
                    block["content"] = content.replace("$pfts_2lqh>$", "").replace(
                        "$<pfts_2lqh$", ""
                    )
                    block_results.append(block)
                out["blocks"] = block_results
            if include_files:
                files = result.get("files", [])
                out["files"] = files[:limit]
            out["has_more"] = bool(result.get("hasMore?")) or any(
                len(out.get(key, [])) >= limit and len(values) > limit
                for key, values in (
                    ("pages", pages if include_pages else []),
                    ("blocks", visible_blocks if include_blocks else []),
                    ("files", files if include_files else []),
                )
            )
        else:
            if include_blocks and not excluded_page_names:
                # Markdown-mode blocks carry block/content but no page
                # identifier, so they cannot be exclusion-filtered — only expose
                # them when no exclusion is active (same rule as snippets)
                out["blocks"] = result.get("blocks", [])[:limit]
            if include_pages:
                pages = [
                    p for p in result.get("pages", [])
                    if p.lower() not in excluded_page_names
                ]
                out["pages"] = pages[:limit]
                if not excluded_page_names:
                    # Snippets carry no page identifier, so they cannot be
                    # exclusion-filtered — only expose them when no exclusion
                    # is active (same rule as text mode)
                    out["pages_content"] = result.get("pages-content", [])[:limit]
            if include_files:
                files = result.get("files", [])
                out["files"] = files[:limit]
            out["has_more"] = bool(result.get("has-more?")) or any(
                len(out.get(key, [])) >= limit and len(values) > limit
                for key, values in (
                    ("blocks", result.get("blocks", []) if include_blocks and not excluded_page_names else []),
                    ("pages", pages if include_pages else []),
                    ("pages_content", result.get("pages-content", []) if include_pages and not excluded_page_names else []),
                    ("files", files if include_files else []),
                )
            )

        return out

    def run_tool(self, args: dict) -> list[TextContent]:
        """Execute search and format results."""
        logger.info(f"Searching with args: {args}")

        if "query" not in args:
            raise RuntimeError("query argument required")

        query = args["query"]
        limit = args.get("limit", 20)
        include_blocks = args.get("include_blocks", True)
        include_pages = args.get("include_pages", True)
        include_files = args.get("include_files", False)

        try:
            # Prepare search options
            search_options = {"limit": limit}

            api = _make_api()
            result = api.search_content(query, search_options)

            if not result:
                return [
                    TextContent(
                        type="text", text=f"No search results found for '{query}'"
                    )
                ]

            # Build excluded page name set (one extra API call only when needed)
            acl = access.get_access_config()
            excluded_page_names = self._build_excluded_page_names(
                api, acl.exclude_tags, acl.exclude_namespaces, acl.include_namespaces
            )

            if args.get("format") == "json":
                json_result = self._build_json_results(
                    result, query, limit, include_blocks, include_pages, include_files, excluded_page_names, api
                )
                return [TextContent(type="text", text=json.dumps(json_result, indent=2))]

            # Format results
            content_parts = []
            content_parts.append(f"# Search Results for '{query}'\n")

            if _get_db_mode():
                content_parts.extend(
                    self._format_db_mode_results(result, limit, include_blocks, include_pages, include_files, excluded_page_names, api)
                )
            else:
                content_parts.extend(
                    self._format_markdown_mode_results(result, limit, include_blocks, include_pages, include_files, excluded_page_names)
                )

            response_text = "\n".join(content_parts)

            return [TextContent(type="text", text=response_text)]

        except Exception as e:
            logger.error(f"Failed to search: {str(e)}")
            return [TextContent(
                type="text",
                text=f"❌ Search failed: {str(e)}"
            )]


class QueryToolHandler(ToolHandler):
    """Execute Logseq DSL queries to search pages and blocks."""

    def __init__(self):
        super().__init__("query")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Execute a Logseq DSL query to search pages and blocks. Supports property queries, tag queries, task queries, and logical combinations. See https://docs.logseq.com/#/page/queries for query syntax.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Logseq DSL query string (e.g., '(page-property status active)', '(and (task todo) (page [[Project]]))')"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 100
                    },
                    "result_type": {
                        "type": "string",
                        "description": "Filter results by type",
                        "enum": ["all", "pages_only", "blocks_only"],
                        "default": "all"
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format (text or json). JSON returns raw result objects including block UUIDs and page info for deep linking.",
                        "enum": ["text", "json"],
                        "default": "text"
                    }
                },
                "required": ["query"]
            }
        )

    def _is_page(self, item: dict) -> bool:
        """Detect if a result item is a page based on available fields."""
        if not isinstance(item, dict):
            return False
        # Pages typically have originalName or name without block-specific fields
        has_page_fields = bool(item.get("originalName") or item.get("name"))
        has_block_content = bool(item.get("content") or item.get("block/content"))
        return has_page_fields and not has_block_content

    def _is_block(self, item: dict) -> bool:
        """Detect if a result item is a block based on available fields."""
        if not isinstance(item, dict):
            return False
        return bool(item.get("content") or item.get("block/content"))

    @staticmethod
    def _block_page_name(item: dict, api) -> str | None:
        """Resolve the owning page name for a DSL block result.

        Prefers the inline 'page' reference carried by the query result; falls
        back to an API lookup by block UUID. Returns None when it cannot be
        determined (callers treat that as fail-closed when rules are set).
        """
        page_ref = item.get("page")
        if isinstance(page_ref, dict):
            name = page_ref.get("originalName") or page_ref.get("name")
            if name:
                return name
        elif isinstance(page_ref, str) and page_ref:
            # A bare UUID string is NOT a trustworthy page name: under an
            # exclude-only policy a UUID matches no rule and would fail OPEN.
            # Resolve the page UUID to its real name so it's fail-closed.
            if _UUID_REF_PATTERN.fullmatch(f"[[{page_ref}]]"):
                return api.resolve_page_uuids([page_ref]).get(page_ref)
            return page_ref
        uuid = item.get("uuid")
        if uuid:
            return api.get_block_page_name(uuid)
        return None

    def _block_blocked(self, item: dict, api, cache: dict | None = None) -> bool:
        """Fail-closed tag AND namespace check for a DSL block result.

        Consulted whenever ANY rule (tag or namespace) is configured. The owning
        page is resolved once via ``_block_page_name``; the block is dropped if
        that page is namespace-blocked OR tag-excluded. A block whose owning page
        cannot be resolved is treated as blocked (fail-closed).

        ``cache`` is an optional per-request memo (page name -> blocked bool) so
        that many blocks sharing an owning page incur the tag fetch only once.
        """
        page_name = self._block_page_name(item, api)
        if page_name is None:
            return True
        if cache is not None and page_name in cache:
            return cache[page_name]

        blocked = self._page_name_blocked(page_name, api)
        if cache is not None:
            cache[page_name] = blocked
        return blocked

    def _page_name_blocked(self, page_name: str, api) -> bool:
        """Tag OR namespace block decision for an already-resolved page name."""
        acl = access.get_access_config()
        if _is_namespace_blocked(page_name, acl.include_namespaces, acl.exclude_namespaces):
            return True
        if acl.exclude_tags:
            # Tag exclusion needs the page's properties; fetch the owning page
            # and inspect its tags. Fail-closed if it cannot be fetched.
            try:
                page = api.get_page_content(page_name)
            except Exception:
                return True
            if page and _is_page_excluded(page.get("page", {}), acl.exclude_tags):
                return True
        return False

    def _format_item(self, item: dict, index: int) -> str:
        """Format a single result item with type indicator."""
        if not isinstance(item, dict):
            return f"{index}. {item}"

        if self._is_page(item):
            name = item.get("originalName") or item.get("name", "<unknown>")
            # Get properties if available
            props = item.get("propertiesTextValues", {}) or item.get("properties", {})
            props_str = ", ".join(f"{k}: {v}" for k, v in props.items()) if props else ""
            if props_str:
                return f"{index}. 📄 **{name}** ({props_str})"
            return f"{index}. 📄 **{name}**"
        elif self._is_block(item):
            content = item.get("content") or item.get("block/content", "")
            # Truncate long content
            if len(content) > 100:
                content = content[:100] + "..."
            return f"{index}. 📝 {content}"
        else:
            # Unknown type - just show what we have
            name = item.get("originalName") or item.get("name") or str(item)[:50]
            return f"{index}. {name}"

    def run_tool(self, args: dict) -> list[TextContent]:
        """Execute DSL query and format results."""
        if "query" not in args:
            raise RuntimeError("query argument required")

        query = args["query"]
        limit = args.get("limit", 100)
        result_type = args.get("result_type", "all")

        try:
            api = _make_api()
            result = api.query_dsl(query)

            if not result:
                return [TextContent(
                    type="text",
                    text=f"No results found for query: `{query}`"
                )]

            # Filter by result_type if specified
            filtered_results = []
            for item in result:
                if result_type == "pages_only" and not self._is_page(item):
                    continue
                if result_type == "blocks_only" and not self._is_block(item):
                    continue
                filtered_results.append(item)

            # Security: filter page objects blocked by tag OR namespace, AND
            # block objects whose owning page is blocked by tag OR namespace.
            # A block's owning page is resolvable (_block_page_name), so its TAGS
            # are checkable too — block filtering must run whenever ANY rule is
            # active (tag-only profiles included). Resolution is fail-closed
            # (unresolvable owning page => dropped).
            acl = access.get_access_config()
            if acl.exclude_tags or acl.include_namespaces or acl.exclude_namespaces:
                filtered = []
                # Per-request memo so blocks sharing an owning page only trigger
                # one tag/namespace resolution + fetch.
                block_decision_cache: dict[str, bool] = {}
                for item in filtered_results:
                    if self._is_page(item):
                        name = item.get("originalName") or item.get("name", "")
                        if _is_page_blocked(item, name):
                            continue
                    elif self._is_block(item):
                        if self._block_blocked(item, api, block_decision_cache):
                            continue
                    filtered.append(item)
                filtered_results = filtered

            if not filtered_results:
                filter_msg = f" (filtered to {result_type})" if result_type != "all" else ""
                return [TextContent(
                    type="text",
                    text=f"No results found for query: `{query}`{filter_msg}"
                )]

            # Apply limit
            limited_results = filtered_results[:limit]

            if args.get("format") == "json":
                json_result = {
                    "query": query,
                    "total": len(filtered_results),
                    "results": limited_results,
                }
                return [TextContent(type="text", text=json.dumps(json_result, indent=2))]

            # Format results
            content_parts = []
            content_parts.append(f"# Query Results\n")
            content_parts.append(f"**Query:** `{query}`\n")

            for i, item in enumerate(limited_results, 1):
                content_parts.append(self._format_item(item, i))

            # Summary
            content_parts.append(f"\n---")
            if len(filtered_results) > limit:
                content_parts.append(f"**Showing {limit} of {len(filtered_results)} results** (increase limit to see more)")
            else:
                content_parts.append(f"**Total: {len(limited_results)} results**")

            return [TextContent(type="text", text="\n".join(content_parts))]

        except Exception as e:
            logger.error(f"Query failed: {str(e)}")
            return [TextContent(
                type="text",
                text=f"❌ Query failed: {str(e)}\n\nMake sure the query syntax is valid. See https://docs.logseq.com/#/page/queries"
            )]


class FindPagesByPropertyToolHandler(ToolHandler):
    """Find pages by property name and optional value."""

    def __init__(self):
        super().__init__("find_pages_by_property")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Find all pages that have a specific property, optionally filtered by value. Simpler alternative to the full query DSL.",
            inputSchema={
                "type": "object",
                "properties": {
                    "property_name": {
                        "type": "string",
                        "description": "Name of the property to search for (e.g., 'status', 'type', 'service')"
                    },
                    "property_value": {
                        "type": "string",
                        "description": "Optional: specific value to match. If omitted, returns all pages that have this property."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 100
                    }
                },
                "required": ["property_name"]
            }
        )

    def _escape_value(self, value: str) -> str:
        """Escape special characters in property values for DSL query."""
        return value.replace('"', '\\"')

    def _validate_property_name(self, name: str) -> str:
        """Validate and return property name, raising if it contains unsafe characters."""
        import re
        if not re.match(r'^[a-zA-Z0-9_\-]+$', name):
            raise ValueError(f"Invalid property name '{name}': only alphanumeric, hyphens, and underscores allowed")
        return name

    def run_tool(self, args: dict) -> list[TextContent]:
        """Find pages by property and format results."""
        if "property_name" not in args:
            raise RuntimeError("property_name argument required")

        try:
            property_name = self._validate_property_name(args["property_name"])
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {str(e)}")]
        property_value = args.get("property_value")
        limit = args.get("limit", 100)

        # Build the DSL query
        if property_value:
            escaped_value = self._escape_value(property_value)
            query = f'(page-property {property_name} "{escaped_value}")'
        else:
            query = f'(page-property {property_name})'

        try:
            api = _make_api()
            result = api.query_dsl(query)

            if not result:
                if property_value:
                    msg = f"No pages found with property '{property_name} = {property_value}'"
                else:
                    msg = f"No pages found with property '{property_name}'"
                return [TextContent(type="text", text=msg)]

            # Security: drop pages blocked by tag OR namespace before limiting
            acl = access.get_access_config()
            if acl.exclude_tags or acl.include_namespaces or acl.exclude_namespaces:
                kept = []
                for item in result:
                    if isinstance(item, dict):
                        name = item.get("originalName") or item.get("name", "")
                        if _is_page_blocked(item, name):
                            continue
                    kept.append(item)
                result = kept

            # Apply limit
            limited_results = result[:limit]

            # Format results
            content_parts = []

            if property_value:
                content_parts.append(f"# Pages with '{property_name} = {property_value}'\n")
            else:
                content_parts.append(f"# Pages with property '{property_name}'\n")

            for item in limited_results:
                if isinstance(item, dict):
                    name = item.get("originalName") or item.get("name", "<unknown>")
                    props = item.get("propertiesTextValues", {}) or item.get("properties", {})

                    # Show the property value if we searched without a specific value
                    if not property_value and property_name in props:
                        content_parts.append(f"- **{name}** ({property_name}: {props[property_name]})")
                    elif not property_value and property_name.lower() in props:
                        content_parts.append(f"- **{name}** ({property_name}: {props[property_name.lower()]})")
                    else:
                        content_parts.append(f"- **{name}**")
                else:
                    content_parts.append(f"- {item}")

            # Summary
            content_parts.append(f"\n---")
            if len(result) > limit:
                content_parts.append(f"**Showing {limit} of {len(result)} pages** (increase limit to see more)")
            else:
                content_parts.append(f"**Total: {len(limited_results)} pages**")

            return [TextContent(type="text", text="\n".join(content_parts))]

        except Exception as e:
            logger.error(f"Property search failed: {str(e)}")
            return [TextContent(
                type="text",
                text=f"❌ Search failed: {str(e)}"
            )]
class GetPagesFromNamespaceToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("get_pages_from_namespace")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Get all pages within a namespace hierarchy (flat list). Use this to discover subpages of a parent page.",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "The namespace to query (e.g., 'Customer', 'Projects/2024')"
                    }
                },
                "required": ["namespace"]
            }
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if "namespace" not in args:
            raise RuntimeError("namespace argument required")

        _enforce_namespace_access(args["namespace"])

        try:
            api = _make_api()
            result = api.get_pages_from_namespace(args["namespace"])

            # Security: silently drop pages blocked by tag OR namespace, e.g. an
            # excluded sub-namespace (work/secret) under an allowed parent (work).
            if result:
                result = [
                    p for p in result
                    if not _is_page_blocked(p, p.get('originalName') or p.get('name') or '')
                ]

            if not result:
                return [TextContent(
                    type="text",
                    text=f"No pages found in namespace '{args['namespace']}'"
                )]

            # Format pages for display
            pages_info = []
            for page in result:
                name = page.get('originalName') or page.get('name', '<unknown>')
                pages_info.append(f"- {name}")

            pages_info.sort()

            response = f"Pages in namespace '{args['namespace']}':\n\n"
            response += "\n".join(pages_info)
            response += f"\n\nTotal: {len(pages_info)} pages"

            return [TextContent(type="text", text=response)]

        except Exception as e:
            logger.error(f"Failed to get pages from namespace: {str(e)}")
            return [TextContent(type="text", text=f"❌ Failed to get pages from namespace '{args['namespace']}': {str(e)}")]


class GetPagesTreeFromNamespaceToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("get_pages_tree_from_namespace")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Get pages within a namespace as a hierarchical tree structure. Useful for understanding the full page hierarchy.",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "The root namespace to build tree from (e.g., 'Projects')"
                    }
                },
                "required": ["namespace"]
            }
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if "namespace" not in args:
            raise RuntimeError("namespace argument required")

        _enforce_namespace_access(args["namespace"])

        try:
            api = _make_api()
            result = api.get_pages_tree_from_namespace(args["namespace"])

            # Security: silently prune nodes blocked by tag OR namespace, e.g. an
            # excluded sub-namespace (work/secret) under an allowed parent (work).
            def prune_blocked(nodes):
                kept = []
                for node in nodes:
                    name = node.get('originalName') or node.get('name') or ''
                    if _is_page_blocked(node, name):
                        continue
                    children = node.get('children', [])
                    if children:
                        node = {**node, 'children': prune_blocked(children)}
                    kept.append(node)
                return kept

            if result:
                result = prune_blocked(result)

            if not result:
                return [TextContent(
                    type="text",
                    text=f"No pages found in namespace '{args['namespace']}'"
                )]

            # Format as tree structure
            def format_tree(pages, prefix="", is_last_list=None):
                if is_last_list is None:
                    is_last_list = []
                lines = []
                for i, page in enumerate(pages):
                    is_last = i == len(pages) - 1
                    name = page.get('originalName') or page.get('name', '<unknown>')

                    # Build the prefix for this line
                    if prefix == "":
                        lines.append(name)
                    else:
                        connector = "└── " if is_last else "├── "
                        lines.append(f"{prefix}{connector}{name}")

                    # Handle children if present
                    children = page.get('children', [])
                    if children:
                        # Build prefix for children
                        if prefix == "":
                            child_prefix = ""
                        else:
                            child_prefix = prefix + ("    " if is_last else "│   ")
                        lines.extend(format_tree(children, child_prefix, is_last_list + [is_last]))
                return lines

            tree_lines = format_tree(result)

            response = f"Page tree for namespace '{args['namespace']}':\n\n"
            response += "\n".join(tree_lines)

            return [TextContent(type="text", text=response)]

        except Exception as e:
            logger.error(f"Failed to get pages tree: {str(e)}")
            return [TextContent(type="text", text=f"❌ Failed to get pages tree for namespace '{args['namespace']}': {str(e)}")]


class RenamePageToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("rename_page")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Rename an existing page. All references throughout the graph will be automatically updated.",
            inputSchema={
                "type": "object",
                "properties": {
                    "old_name": {
                        "type": "string",
                        "description": "Current name of the page"
                    },
                    "new_name": {
                        "type": "string",
                        "description": "New name for the page"
                    }
                },
                "required": ["old_name", "new_name"]
            }
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if "old_name" not in args or "new_name" not in args:
            raise RuntimeError("old_name and new_name arguments required")

        old_name = args["old_name"]
        new_name = args["new_name"]

        _enforce_namespace_access(old_name)
        _enforce_namespace_access(new_name)

        try:
            api = _make_api()
            # Tag-on-write: guard the SOURCE page (existing). The target name is
            # a not-yet-existing page, so it has no prior tags to check.
            _enforce_page_tag_access(api, old_name)
            api.rename_page(old_name, new_name)

            return [TextContent(
                type="text",
                text=f"Successfully renamed page '{old_name}' to '{new_name}'\n"
                     f"All references in the graph have been updated."
            )]
        except AccessDenied:
            raise
        except ValueError as e:
            return [TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )]
        except Exception as e:
            logger.error(f"Failed to rename page: {str(e)}")
            return [TextContent(
                type="text",
                text=f"Failed to rename page: {str(e)}"
            )]


class GetPageBacklinksToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("get_page_backlinks")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Get all pages and blocks that link to a specific page (backlinks/linked references).",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_name": {
                        "type": "string",
                        "description": "Name of the page to find backlinks for"
                    },
                    "include_content": {
                        "type": "boolean",
                        "description": "Whether to include the content of referencing blocks",
                        "default": True
                    }
                },
                "required": ["page_name"]
            }
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if "page_name" not in args:
            raise RuntimeError("page_name argument required")

        page_name = args["page_name"]
        include_content = args.get("include_content", True)

        _enforce_namespace_access(page_name)

        try:
            api = _make_api()
            result = api.get_page_linked_references(page_name)

            if not result:
                return [TextContent(
                    type="text",
                    text=f"No backlinks found for page '{page_name}'"
                )]

            # Format results
            # API returns: [[PageEntity, [BlockEntity, ...]], ...]
            content_parts = []
            content_parts.append(f"# Backlinks for '{page_name}'\n")

            total_refs = 0
            shown_pages = 0

            for item in result:
                if not isinstance(item, list) or len(item) < 2:
                    continue

                page_info, blocks = item[0], item[1]

                # Guard against None page entity (can occur in Logseq DB mode)
                if not isinstance(page_info, dict):
                    continue

                # Get page name
                ref_page_name = page_info.get('originalName') or page_info.get('name', '<unknown>')

                # Security: silently skip referencing pages blocked by namespace.
                # page_info rarely carries 'properties' so tag filtering falls back
                # to namespace-only; pass page_info anyway so tag check fires if
                # properties happen to be present.
                if _is_page_blocked(page_info, ref_page_name):
                    continue
                shown_pages += 1
                block_count = len(blocks) if blocks else 0
                total_refs += block_count

                content_parts.append(f"**{ref_page_name}** ({block_count} reference{'s' if block_count != 1 else ''})")

                # Include block content if requested
                if include_content and blocks:
                    for block in blocks:
                        block_content = block.get('content', '').strip()
                        if block_content:
                            # Truncate long content
                            if len(block_content) > 150:
                                block_content = block_content[:150] + "..."
                            content_parts.append(f"  - {block_content}")

                content_parts.append("")

            # Summary: count only referrers that survived filtering, so the
            # footer never reveals that hidden (blocked) referrers exist.
            page_count = shown_pages
            content_parts.append(f"---\n**Total: {page_count} page{'s' if page_count != 1 else ''}, {total_refs} reference{'s' if total_refs != 1 else ''}**")

            return [TextContent(type="text", text="\n".join(content_parts))]

        except Exception as e:
            logger.error(f"Failed to get backlinks: {str(e)}")
            return [TextContent(
                type="text",
                text=f"Failed to get backlinks: {str(e)}"
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
                        "description": "Optional block properties (e.g., {'marker': 'TODO', 'priority': 'A'})",
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

        try:
            api = _make_api()
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


class SetBlockPropertiesToolHandler(ToolHandler):
    def __init__(self):
        super().__init__("set_block_properties")

    def get_tool_description(self):
        return Tool(
            name=self.name,
            description="Set properties on a block in Logseq DB-mode. Properties must be defined on the block's tag/class. Use property display names (e.g. 'Content status', not the internal ident).",
            inputSchema={
                "type": "object",
                "properties": {
                    "block_uuid": {
                        "type": "string",
                        "description": "UUID of the block to update",
                    },
                    "properties": {
                        "type": "object",
                        "description": "Properties to set as {name: value} pairs. Use display names (e.g. 'Content status': 'kiem')",
                        "additionalProperties": True,
                    },
                },
                "required": ["block_uuid", "properties"],
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        """Set DB-mode properties on a block."""
        if not _get_db_mode():
            return [TextContent(
                type="text",
                text="❌ set_block_properties requires LOGSEQ_DB_MODE=true (only works with Logseq DB-mode graphs)",
            )]

        if "block_uuid" not in args or "properties" not in args:
            raise RuntimeError("block_uuid and properties arguments required")

        block_uuid = args["block_uuid"]
        properties = args["properties"]

        try:
            api = _make_api()
            _enforce_block_namespace_access(api, block_uuid)
            _enforce_block_tag_access(api, block_uuid)
            results = []

            for prop_name, value in properties.items():
                # Resolve display name to ident
                ident = api.resolve_property_ident(prop_name)
                if not ident:
                    results.append(f"⚠️ Property '{prop_name}' not found")
                    continue

                api._upsert_block_property(block_uuid, ident, value)
                results.append(f"✅ {prop_name} = {value}")

            return [TextContent(
                type="text",
                text=f"Set properties on block {block_uuid}:\n" + "\n".join(results),
            )]

        except AccessDenied:
            raise
        except Exception as e:
            logger.error(f"Failed to set block properties: {str(e)}")
            return [TextContent(
                type="text",
                text=f"❌ Failed to set block properties: {str(e)}",
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
                            "id: '<uuid>' (required for edit), "
                            "data: {title: '<content>'}}. Link by UUID — "
                            "[[<page-uuid>]] — never by page name."
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

        if not _get_db_mode():
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
            api = _make_api()
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

        if not _get_db_mode():
            return [TextContent(
                type="text",
                text="get_page_data is available only for Logseq 2.x DB graphs. "
                "Set LOGSEQ_DB_MODE=true.",
            )]

        try:
            api = _make_api()
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
                    "expand": {"type": "boolean", "default": False},
                },
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if not _get_db_mode():
            return [TextContent(
                type="text",
                text="list_tags is available only for Logseq 2.x DB graphs. "
                "Set LOGSEQ_DB_MODE=true.",
            )]
        try:
            result = _make_api().list_tags(expand=bool(args.get("expand", False)))
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
                    "expand": {"type": "boolean", "default": False},
                },
            },
        )

    def run_tool(self, args: dict) -> list[TextContent]:
        if not _get_db_mode():
            return [TextContent(
                type="text",
                text="list_properties is available only for Logseq 2.x DB graphs. "
                "Set LOGSEQ_DB_MODE=true.",
            )]
        try:
            result = _make_api().list_properties(expand=bool(args.get("expand", False)))
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=f"Failed to list properties: {str(e)}")]


class _DBToolHandler(ToolHandler):
    def _db_only(self) -> list[TextContent] | None:
        if not _get_db_mode():
            return [TextContent(
                type="text",
                text=f"{self.name} is available only for Logseq 2.x DB graphs. "
                "Set LOGSEQ_DB_MODE=true.",
            )]
        return None

    def _execute(self, args: dict) -> list[TextContent]:
        blocked = self._db_only()
        if blocked:
            return blocked
        try:
            result = self._call(_make_api(), args)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except AccessDenied:
            raise
        except Exception as e:
            return [TextContent(type="text", text=f"{self.name} failed: {str(e)}")]

    def _call(self, api, args: dict):
        raise NotImplementedError


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
        return Tool(name=self.name, description="Create or update a typed DB graph property.", inputSchema={
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


class GetBlockPropertiesToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("get_block_properties")
    def get_tool_description(self):
        return Tool(name=self.name, description="Get all typed properties on a DB node.", inputSchema={
            "type": "object", "properties": {"block_uuid": {"type": "string"}},
            "required": ["block_uuid"],
        })
    def _call(self, api, args):
        _enforce_block_namespace_access(api, args["block_uuid"])
        _enforce_block_tag_access(api, args["block_uuid"])
        return api.get_block_properties(args["block_uuid"])
    def run_tool(self, args):
        if "block_uuid" not in args: raise RuntimeError("block_uuid argument required")
        return self._execute(args)


class GetBlockPropertyToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("get_block_property")
    def get_tool_description(self):
        return Tool(name=self.name, description="Get one typed property from a DB node.", inputSchema={
            "type": "object", "properties": {
                "block_uuid": {"type": "string"}, "property_name": {"type": "string"},
            }, "required": ["block_uuid", "property_name"],
        })
    def _call(self, api, args):
        _enforce_block_namespace_access(api, args["block_uuid"])
        _enforce_block_tag_access(api, args["block_uuid"])
        return api.get_block_property(args["block_uuid"], args["property_name"])
    def run_tool(self, args):
        for key in ("block_uuid", "property_name"):
            if key not in args: raise RuntimeError(f"{key} argument required")
        return self._execute(args)


class UpsertBlockPropertyToolHandler(_DBToolHandler):
    def __init__(self): super().__init__("upsert_block_property")
    def get_tool_description(self):
        return Tool(name=self.name, description="Set a typed property on a DB node.", inputSchema={
            "type": "object", "properties": {
                "block_uuid": {"type": "string"}, "property_name": {"type": "string"},
                "value": {}, "options": {"type": "object"},
            }, "required": ["block_uuid", "property_name", "value"],
        })
    def _call(self, api, args):
        _enforce_block_namespace_access(api, args["block_uuid"])
        _enforce_block_tag_access(api, args["block_uuid"])
        return api.upsert_block_property(args["block_uuid"], args["property_name"], args["value"], args.get("options"))
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
        _enforce_block_namespace_access(api, args["block_uuid"])
        _enforce_block_tag_access(api, args["block_uuid"])
        return api._call_api("logseq.Editor.removeBlockProperty", [args["block_uuid"], args["property_name"]])
    def run_tool(self, args):
        for key in ("block_uuid", "property_name"):
            if key not in args: raise RuntimeError(f"{key} argument required")
        return self._execute(args)


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
        return Tool(name=self.name, description="Create a DB graph tag/class.", inputSchema={
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
        _enforce_block_namespace_access(api, args["block_uuid"])
        _enforce_block_tag_access(api, args["block_uuid"])
        return api.add_block_tag(args["block_uuid"], args["tag"])
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
        _enforce_block_namespace_access(api, args["block_uuid"])
        _enforce_block_tag_access(api, args["block_uuid"])
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


# Preserve the declarative access-policy surface used by the server's security audit.
CreatePageToolHandler.access_policy = [access.NamespaceName("title")]
GetPageContentToolHandler.access_policy = [access.NamespaceName("page_name")]
DeletePageToolHandler.access_policy = [
    access.NamespaceName("page_name"), access.PageTag("page_name")
]
UpdatePageToolHandler.access_policy = [
    access.NamespaceName("page_name"), access.PageTag("page_name")
]
RenamePageToolHandler.access_policy = [
    access.NamespaceName("old_name"),
    access.NamespaceName("new_name"),
    access.PageTag("old_name"),
]
GetPageBacklinksToolHandler.access_policy = [access.NamespaceName("page_name")]
for _handler in (
    DeleteBlockToolHandler,
    UpdateBlockToolHandler,
    GetBlockToolHandler,
    SetBlockPropertiesToolHandler,
):
    _handler.access_policy = [
        access.BlockNamespace("block_uuid"), access.BlockTag("block_uuid")
    ]
InsertNestedBlockToolHandler.access_policy = [
    access.BlockNamespace("parent_block_uuid"),
    access.BlockTag("parent_block_uuid"),
]
GetPagesFromNamespaceToolHandler.access_policy = [access.NamespaceName("namespace")]
GetPagesTreeFromNamespaceToolHandler.access_policy = [access.NamespaceName("namespace")]

__all__ = [
    "ToolHandler", "AccessDenied", "CreatePageToolHandler", "ListPagesToolHandler",
    "GetPageContentToolHandler", "DeletePageToolHandler", "UpdatePageToolHandler",
    "DeleteBlockToolHandler", "UpdateBlockToolHandler", "GetBlockToolHandler",
    "SearchToolHandler", "QueryToolHandler", "FindPagesByPropertyToolHandler",
    "GetPagesFromNamespaceToolHandler", "GetPagesTreeFromNamespaceToolHandler",
    "RenamePageToolHandler", "GetPageBacklinksToolHandler",
    "InsertNestedBlockToolHandler", "SetBlockPropertiesToolHandler",
    "UpsertNodesToolHandler", "GetPageDataToolHandler", "ListTagsToolHandler",
    "ListPropertiesToolHandler",
    "SearchBlocksToolHandler", "GetPropertyToolHandler", "UpsertPropertyToolHandler",
    "RemovePropertyToolHandler", "GetBlockPropertiesToolHandler",
    "GetBlockPropertyToolHandler", "UpsertBlockPropertyToolHandler",
    "RemoveBlockPropertyToolHandler", "GetTagToolHandler", "GetTagObjectsToolHandler",
    "GetTagsByNameToolHandler", "CreateTagToolHandler", "AddBlockTagToolHandler",
    "RemoveBlockTagToolHandler",
    "AddTagPropertyToolHandler", "RemoveTagPropertyToolHandler",
    "AddTagExtendsToolHandler", "RemoveTagExtendsToolHandler",
]
