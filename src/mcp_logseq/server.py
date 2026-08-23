import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from typing import Any
import os
import requests
from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    CallToolResult,
    ListToolsResult,
)

try:
    sys.stderr.reconfigure(errors="backslashreplace")
except (AttributeError, OSError):
    pass

# Configure logging to stderr with more verbose output
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp-logseq")

# Add a file handler to keep logs (in user's home directory to avoid permission issues)
log_dir = os.path.expanduser("~/.cache/mcp-logseq")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "mcp_logseq.log")
try:
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.debug(f"Logging to: {log_file}")
except Exception as e:
    # If file logging fails, continue without it
    logger.warning(f"Could not setup file logging: {e}")
    pass

load_dotenv()

from . import tools

# Load environment variables with more verbose logging
# Names of the genuine write tools — tools that mutate Logseq content. When
# ``read_only`` is set these are NOT registered. ``sync_vector_db`` is NOT in
# this set: it mutates the (local) vector index, not Logseq content, and stays
# registered (Task 5b makes it inert under read-only).
_WRITE_TOOL_NAMES = frozenset(
    {
        "create_page",
        "update_page",
        "delete_page",
        "rename_page",
        "update_block",
        "delete_block",
        "insert_nested_block",
        "set_block_properties",
        "upsert_nodes",
        "upsert_property",
        "remove_property",
        "upsert_block_property",
        "remove_block_property",
        "create_tag",
        "add_block_tag",
        "remove_block_tag",
        "remove_tag_property",
        "remove_tag_extends",
    }
)

_DB_ONLY_TOOL_NAMES = frozenset(
    {
        "upsert_nodes",
        "get_page_data",
        "list_tags",
        "list_properties",
        "search_blocks",
        "get_property",
        "upsert_property",
        "remove_property",
        "get_block_properties",
        "get_block_property",
        "upsert_block_property",
        "remove_block_property",
        "get_tag",
        "get_tag_objects",
        "get_tags_by_name",
        "create_tag",
        "add_block_tag",
        "remove_block_tag",
        "add_tag_property",
        "remove_tag_property",
        "add_tag_extends",
        "remove_tag_extends",
        "set_block_properties",
    }
)

_FILE_ONLY_TOOL_NAMES = frozenset(
    {
        "create_page",
        "update_page",
        "delete_page",
        "get_page_content",
        "search",
        "query",
        "find_pages_by_property",
        "get_pages_from_namespace",
        "get_pages_tree_from_namespace",
        "rename_page",
        "get_page_backlinks",
    }
)


def _forced_graph_profile() -> str:
    """Return a compact tool profile only when graph mode is explicitly forced."""
    mode = os.getenv("LOGSEQ_DB_MODE", "auto").strip().lower()
    if mode in {"1", "true", "yes"}:
        return "db"
    if mode in {"0", "false", "no"}:
        return "file"
    return "auto"


def _read_tool_timeout() -> float:
    """Return the total deadline for read tools without affecting writes."""
    raw_value = os.getenv("MCP_READ_TOOL_TIMEOUT", "90").strip()
    try:
        timeout = float(raw_value)
    except ValueError:
        timeout = 90.0
    return timeout if timeout > 0 else 90.0


def _max_read_response_chars() -> int:
    """Return the maximum read-response size, or zero to disable the guard."""
    raw_value = os.getenv("MCP_MAX_RESPONSE_CHARS", "30000").strip()
    try:
        limit = int(raw_value)
    except ValueError:
        limit = 30000
    return max(limit, 0)


def _bound_read_content(name: str, content: Sequence[TextContent]) -> list[TextContent]:
    """Keep oversized read responses useful without emitting invalid JSON."""
    limit = _max_read_response_chars()
    if not limit:
        return list(content)

    bounded: list[TextContent] = []
    for item in content:
        if len(item.text) <= limit:
            bounded.append(item)
            continue

        try:
            json.loads(item.text)
        except (TypeError, ValueError):
            text = (
                item.text[:limit]
                + "\n\n[Response truncated. Narrow the request or use its limit/depth options.]"
            )
        else:
            text = json.dumps(
                {
                    "truncated": True,
                    "tool": name,
                    "message": "Response exceeded the configured size limit. Narrow the request or use its limit/depth options.",
                }
            )
        bounded.append(TextContent(type="text", text=text))
    return bounded


def _transport_error_message(error: Exception) -> str:
    """Describe common Logseq transport failures without exposing a traceback."""
    if isinstance(error, requests.Timeout):
        return "Logseq did not respond before the HTTP timeout. Verify its API server, then retry the read; a timed-out write may have committed."
    if isinstance(error, requests.ConnectionError):
        return "Unable to connect to Logseq's HTTP API. Confirm Logseq is running and its API server is started."
    if isinstance(error, requests.HTTPError):
        response = error.response
        status = response.status_code if response is not None else "unknown"
        return f"Logseq's HTTP API returned status {status}. Check the method arguments and API token."
    if isinstance(error, (json.JSONDecodeError, requests.JSONDecodeError)):
        return "Logseq returned an empty or invalid JSON response. Retry a read after confirming the API server is healthy."
    return str(error)


def _register_all_tool_handlers(handlers: dict, read_only: bool = False) -> None:
    """Populate ``handlers`` with every available ToolHandler instance.

    Mutates the provided dict in place so callers can wire ``list_tools`` /
    ``call_tool`` closures over the same registry.

    When ``read_only`` is True, the genuine write handlers (see
    ``_WRITE_TOOL_NAMES``) are skipped; all read tools plus ``sync_vector_db``,
    ``vector_search`` and ``vector_db_status`` remain registered.
    """

    profile = _forced_graph_profile()

    def add(tool_class: tools.ToolHandler) -> None:
        if read_only and tool_class.name in _WRITE_TOOL_NAMES:
            logger.info(f"read_only: skipping write tool handler: {tool_class.name}")
            return
        if profile == "db" and tool_class.name in _FILE_ONLY_TOOL_NAMES:
            logger.info(f"db profile: skipping file-only tool handler: {tool_class.name}")
            return
        if profile == "file" and tool_class.name in _DB_ONLY_TOOL_NAMES:
            logger.info(f"file profile: skipping DB-only tool handler: {tool_class.name}")
            return
        logger.debug(f"Registering tool handler: {tool_class.name}")
        handlers[tool_class.name] = tool_class
        logger.info(f"Successfully registered tool handler: {tool_class.name}")

    logger.info(f"Registering tool handlers (read_only={read_only}, profile={profile})...")

    add(tools.UpsertNodesToolHandler())
    add(tools.GetPageDataToolHandler())
    add(tools.ListTagsToolHandler())
    add(tools.ListPropertiesToolHandler())
    add(tools.SearchBlocksToolHandler())
    add(tools.GetPropertyToolHandler())
    add(tools.UpsertPropertyToolHandler())
    add(tools.RemovePropertyToolHandler())
    add(tools.GetBlockPropertiesToolHandler())
    add(tools.GetBlockPropertyToolHandler())
    add(tools.UpsertBlockPropertyToolHandler())
    add(tools.RemoveBlockPropertyToolHandler())
    add(tools.GetTagToolHandler())
    add(tools.GetTagObjectsToolHandler())
    add(tools.GetTagsByNameToolHandler())
    add(tools.CreateTagToolHandler())
    add(tools.AddBlockTagToolHandler())
    add(tools.RemoveBlockTagToolHandler())
    add(tools.AddTagPropertyToolHandler())
    add(tools.RemoveTagPropertyToolHandler())
    add(tools.AddTagExtendsToolHandler())
    add(tools.RemoveTagExtendsToolHandler())
    add(tools.CreatePageToolHandler())
    add(tools.UpdatePageToolHandler())
    add(tools.ListPagesToolHandler())
    add(tools.GetPageContentToolHandler())
    add(tools.DeletePageToolHandler())
    add(tools.DeleteBlockToolHandler())
    add(tools.UpdateBlockToolHandler())
    add(tools.GetBlockToolHandler())
    add(tools.SearchToolHandler())
    add(tools.QueryToolHandler())
    add(tools.FindPagesByPropertyToolHandler())
    add(tools.GetPagesFromNamespaceToolHandler())
    add(tools.GetPagesTreeFromNamespaceToolHandler())
    add(tools.RenamePageToolHandler())
    add(tools.GetPageBacklinksToolHandler())
    add(tools.InsertNestedBlockToolHandler())
    add(tools.SetBlockPropertiesToolHandler())
    logger.info("Tool handlers registration complete")

    # Conditional vector tool registration — only when LOGSEQ_CONFIG_FILE is set
    # and vector.enabled is true in the config file
    try:
        from .config import load_vector_config, load_exclude_tags
        vector_config = load_vector_config()
        # Merge top-level exclude_tags into vector config (additive union)
        top_level_exclude = load_exclude_tags()
        if vector_config and top_level_exclude:
            merged = list(dict.fromkeys(top_level_exclude + vector_config.exclude_tags))
            vector_config.exclude_tags = merged
        if vector_config and vector_config.enabled:
            from .vector.index import (
                VectorDBStatusToolHandler,
                VectorSearchToolHandler,
                SyncVectorDBToolHandler,
            )
            add(VectorSearchToolHandler(vector_config))
            add(SyncVectorDBToolHandler(vector_config))
            add(VectorDBStatusToolHandler(vector_config))
            logger.info("Vector search tools registered (3 tools)")
        else:
            logger.debug("Vector search not configured — skipping vector tools")
    except Exception as e:
        logger.warning(f"Could not load vector config, vector tools disabled: {e}")


def build_app(read_only: bool = False) -> tuple[Server, dict]:
    """Build a fully wired MCP ``Server`` plus its tool-handler registry.

    Returns ``(server, handlers)`` where ``handlers`` is the very same dict the
    server's ``list_tools`` / ``call_tool`` closures read from. Mutating that
    dict after construction is therefore reflected by the served app.

    When ``read_only`` is True the genuine write tools are not registered, so
    the served app exposes only read/search tools (plus the vector tools,
    including ``sync_vector_db``). Default ``read_only=False`` registers
    everything, identical to prior behavior.
    """
    handlers: dict = {}
    _register_all_tool_handlers(handlers, read_only)

    async def list_tools(_context, _params) -> ListToolsResult:
        """List available tools."""
        logger.debug("Listing tools")
        tools_list = [th.get_tool_description() for th in handlers.values()]
        logger.debug(f"Found {len(tools_list)} tools")
        return ListToolsResult(tools=tools_list)

    async def call_tool(_context, request) -> CallToolResult:
        """Handle tool calls."""
        name = request.name
        arguments = request.arguments or {}
        logger.info(f"Tool call: {name} with arguments {arguments}")

        if not isinstance(arguments, dict):
            logger.error("Arguments must be dictionary")
            raise RuntimeError("arguments must be dictionary")

        tool_handler = handlers.get(name)
        if not tool_handler:
            logger.error(f"Unknown tool: {name}")
            raise ValueError(f"Unknown tool: {name}")

        try:
            logger.debug(f"Running tool {name}")
            if name in _WRITE_TOOL_NAMES:
                result = await asyncio.to_thread(tool_handler.run_tool, arguments)
            else:
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(tool_handler.run_tool, arguments),
                        timeout=_read_tool_timeout(),
                    )
                except TimeoutError:
                    return CallToolResult(
                        content=[TextContent(
                            type="text",
                            text=(
                                f"Read tool '{name}' exceeded the { _read_tool_timeout():g }s "
                                "deadline. Check Logseq's HTTP API and retry the read."
                            ),
                        )],
                        isError=True,
                    )
                result = _bound_read_content(name, result)
            logger.debug(f"Tool result: {result}")
            return CallToolResult(content=result)
        except Exception as e:
            logger.error(f"Error running tool: {str(e)}", exc_info=True)
            return CallToolResult(
                content=[TextContent(type="text", text=f"Error: {_transport_error_message(e)}")],
                isError=True,
            )

    server = Server(
        "mcp-logseq",
        version="1.8.0",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )

    return server, handlers


# ---------------------------------------------------------------------------
# Backward-compatible module-level surface.
#
# Existing code/tests import ``app``, ``tool_handlers``, ``add_tool_handler``
# and ``get_tool_handler`` from this module. The module-level ``tool_handlers``
# IS the dict that ``app``'s closures serve from — registration happens exactly
# once — so ``add_tool_handler(X)`` after import is visible through ``app``.
# ---------------------------------------------------------------------------

app, tool_handlers = build_app()


def add_tool_handler(tool_class: tools.ToolHandler):
    logger.debug(f"Registering tool handler: {tool_class.name}")
    tool_handlers[tool_class.name] = tool_class
    logger.info(f"Successfully registered tool handler: {tool_class.name}")


def get_tool_handler(name: str) -> tools.ToolHandler | None:
    logger.debug(f"Looking for tool handler: {name}")
    handler = tool_handlers.get(name)
    if handler is None:
        logger.warning(f"Tool handler not found: {name}")
    else:
        logger.debug(f"Found tool handler: {name}")
    return handler


async def main(read_only: bool = False):
    logger.info(f"Starting LogSeq MCP server (read_only={read_only})")
    from mcp.server.stdio import stdio_server

    app, _ = build_app(read_only=read_only)
    async with stdio_server() as (read_stream, write_stream):
        logger.info("Initializing server...")
        await app.run(read_stream, write_stream, app.create_initialization_options())
