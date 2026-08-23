import json
import os
import re
import logging
import threading
import uuid
from typing import Any
from urllib.parse import urlparse
from .. import logseq
from .. import parser
from .. import access
from ..settings import load_settings
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
        block.get("block/title") or block.get("title") or block.get("content") or ""
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
    allowed_data_keys = {
        ("add", "block"): {"title", "page-id", "tags"},
        ("add", "page"): {"title", "tags"},
        ("add", "tag"): {"title"},
        ("add", "property"): {"title"},
        ("edit", "block"): {"title"},
        ("edit", "page"): {"title"},
        ("edit", "tag"): {"title"},
        ("edit", "property"): {"title"},
    }
    strict = os.getenv("LOGSEQ_UPSERT_STRICT", "true").lower() not in {
        "0", "false", "no"
    }
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
        allowed = allowed_data_keys[(operation_type, entity_type)]
        unknown = set(data) - allowed
        if strict and unknown:
            raise ValueError(
                f"operation {index} has unsupported data key(s) {sorted(unknown)} for "
                f"{operation_type} {entity_type}. Allowed keys: {sorted(allowed)}."
            )
        if operation_type == "edit":
            operation_id = operation.get("id")
            if not isinstance(operation_id, str):
                raise ValueError(f"operation {index} edit requires a string id")
            try:
                uuid.UUID(operation_id)
            except ValueError as error:
                raise ValueError(f"operation {index} edit id must be a UUID") from error
            # Live-tested on Logseq 2.0.1: an edit without title is rejected/
            # unreliable, unlike add's per-entity title requirement below.
            if not isinstance(data.get("title"), str) or not data["title"].strip():
                raise ValueError(f"operation {index} edit requires title")
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




class _DBToolHandler(ToolHandler):
    # Set on a subclass to permanently refuse a call that is confirmed (via
    # live testing against Logseq 2.0.1) to hang rather than error, instead of
    # letting the MCP call block for the full HTTP timeout.
    hang_confirmed_message: str | None = None

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
        self._access_check(_make_api(), args)
        if self.hang_confirmed_message:
            return [TextContent(type="text", text=self.hang_confirmed_message)]
        try:
            result = self._call(_make_api(), args)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except AccessDenied:
            raise
        except Exception as e:
            return [TextContent(type="text", text=f"{self.name} failed: {str(e)}")]

    def _access_check(self, api, args: dict) -> None:
        """Override to enforce access control before hang_confirmed_message short-circuits _call."""
        return None

    def _call(self, api, args: dict):
        raise NotImplementedError




from .pages import (
    CreatePageToolHandler, ListPagesToolHandler, GetPageContentToolHandler,
    DeletePageToolHandler, UpdatePageToolHandler, GetPagesFromNamespaceToolHandler,
    GetPagesTreeFromNamespaceToolHandler, RenamePageToolHandler, GetPageBacklinksToolHandler,
)
from .blocks import (
    DeleteBlockToolHandler, UpdateBlockToolHandler, GetBlockToolHandler,
    InsertNestedBlockToolHandler,
)
from .search import SearchToolHandler, QueryToolHandler, FindPagesByPropertyToolHandler
from .db_native import (
    SetBlockPropertiesToolHandler, UpsertNodesToolHandler, GetPageDataToolHandler,
    ListTagsToolHandler, ListPropertiesToolHandler, SearchBlocksToolHandler,
)
from .properties import (
    GetPropertyToolHandler, UpsertPropertyToolHandler, RemovePropertyToolHandler,
    GetBlockPropertiesToolHandler, GetBlockPropertyToolHandler,
    UpsertBlockPropertyToolHandler, RemoveBlockPropertyToolHandler,
)
from .tags import (
    GetTagToolHandler, GetTagObjectsToolHandler, GetTagsByNameToolHandler,
    CreateTagToolHandler, AddBlockTagToolHandler, RemoveBlockTagToolHandler,
    AddTagPropertyToolHandler, RemoveTagPropertyToolHandler,
    AddTagExtendsToolHandler, RemoveTagExtendsToolHandler,
)


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
