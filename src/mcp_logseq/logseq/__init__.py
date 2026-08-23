import requests
import logging
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger("mcp-logseq")


@dataclass(frozen=True)
class GraphOperationRoute:
    """Method mapping for one logical MCP operation across graph models.

    File graphs always use ``file_method`` (``logseq.Editor.*``). DB graphs
    always use ``db_method`` (``logseq.cli.*``/``logseq.app.*``) when
    ``db_status`` is "verified" — there is no cross-namespace fallback. An
    operation whose DB route is "rejected" (confirmed unsafe, e.g. hangs) or
    "untested" is simply unavailable on DB graphs.
    """

    file_method: str | None
    db_method: str | None
    db_status: str
    notes: str = ""


GRAPH_OPERATION_ROUTES: dict[str, GraphOperationRoute] = {
    "list_pages": GraphOperationRoute(
        "logseq.Editor.getAllPages", "logseq.cli.listPages", "verified"
    ),
    "list_tags": GraphOperationRoute(
        None, "logseq.cli.listTags", "verified"
    ),
    "list_properties": GraphOperationRoute(
        None, "logseq.cli.listProperties", "verified"
    ),
    "search": GraphOperationRoute(
        "logseq.App.search", "logseq.app.search", "verified"
    ),
    "get_page_data": GraphOperationRoute(
        None, "logseq.cli.getPageData", "verified"
    ),
    "upsert_nodes": GraphOperationRoute(
        None, "logseq.cli.upsertNodes", "verified"
    ),
    "get_property": GraphOperationRoute(
        "logseq.Editor.getProperty", "logseq.cli.getProperty", "verified"
    ),
    "get_tag": GraphOperationRoute(
        "logseq.Editor.getTag", "logseq.cli.getTag", "verified"
    ),
    "get_tags_by_name": GraphOperationRoute(
        "logseq.Editor.getTagsByName", "logseq.cli.getTagsByName", "verified"
    ),
    "get_tag_objects": GraphOperationRoute(
        "logseq.Editor.getTagObjects", "logseq.cli.getTagObjects", "verified"
    ),
    "create_tag": GraphOperationRoute(
        "logseq.Editor.createTag", "logseq.cli.createTag", "verified",
        notes="Both namespaces mint the same :plugin.class._test_plugin/* junk ident for "
        "externally-called (non-plugin) writes; that's Logseq's ownership model, not a bug.",
    ),
    "add_tag_property": GraphOperationRoute(
        "logseq.Editor.addTagProperty", "logseq.cli.addTagProperty", "verified"
    ),
    "remove_tag_property": GraphOperationRoute(
        "logseq.Editor.removeTagProperty", "logseq.cli.removeTagProperty", "verified"
    ),
    # Live-tested against Logseq 2.0.1 on 2026-08-23: each cli.* candidate
    # below hangs indefinitely (curl timeout, HTTP 0), while other cli.*
    # calls made immediately before/after each one stayed responsive (ruling
    # out a global wedge masking a per-method issue). No Editor.* fallback —
    # these operations are simply unavailable on DB graphs.
    "get_block": GraphOperationRoute(
        "logseq.Editor.getBlock", "logseq.cli.getBlock", "rejected",
        notes="logseq.cli.getBlock hangs (HTTP 0) for both includeChildren=true and false.",
    ),
    "get_block_properties": GraphOperationRoute(
        "logseq.Editor.getBlockProperties", "logseq.cli.getBlockProperties", "rejected",
        notes="logseq.cli.getBlockProperties hangs (HTTP 0) even with a bare block UUID argument.",
    ),
    "get_block_property": GraphOperationRoute(
        "logseq.Editor.getBlockProperty", "logseq.cli.getBlockProperty", "rejected",
        notes="logseq.cli.getBlockProperty hangs (HTTP 0).",
    ),
    "add_tag_extends": GraphOperationRoute(
        "logseq.Editor.addTagExtends", "logseq.cli.addTagExtends", "rejected",
        notes="logseq.cli.addTagExtends hangs (HTTP 0) with tag-only arguments.",
    ),
    "remove_tag_extends": GraphOperationRoute(
        "logseq.Editor.removeTagExtends", "logseq.cli.removeTagExtends", "rejected",
        notes="logseq.cli.removeTagExtends hangs (HTTP 0).",
    ),
    "update_block": GraphOperationRoute(
        "logseq.Editor.updateBlock", "logseq.cli.updateBlock", "rejected",
        notes="logseq.cli.updateBlock hangs (HTTP 0).",
    ),
    "create_page": GraphOperationRoute(
        "logseq.Editor.createPage", "logseq.cli.createPage", "rejected",
        notes="logseq.cli.createPage hangs (HTTP 0) even for a brand-new page.",
    ),
    "upsert_property": GraphOperationRoute(
        "logseq.Editor.upsertProperty", "logseq.cli.upsertProperty", "rejected",
        notes="logseq.cli.upsertProperty returns HTTP 500 'Plugins can only upsert its "
        "own properties' for external (non-plugin) callers — Logseq's ownership model, "
        "not fixable by namespace choice.",
    ),
    # Not yet live-tested against a cli.* candidate. Unavailable on DB graphs
    # until verified — no fallback to Editor.* under the hard File/DB split.
    # Live-tested against Logseq 2.0.1 on 2026-08-23 (second pass, the
    # previously-"untested" operations): each cli.* candidate below was
    # bracketed with a cli.listPages responsiveness check immediately after
    # every hang, ruling out a global wedge masking a per-method issue.
    "delete_block": GraphOperationRoute(
        "logseq.Editor.removeBlock", None, "rejected",
        notes="logseq.cli.removeBlock hangs (HTTP 0). No batch 'remove' op in "
        "upsertNodes either; there is no working DB deletion route yet.",
    ),
    "insert_block": GraphOperationRoute(
        "logseq.Editor.insertBlock", None, "rejected",
        notes="logseq.cli.insertBlock hangs (HTTP 0). Use upsert_nodes to add a "
        "block (entityType='block', data={'title','page-id','tags'}) instead.",
    ),
    "remove_property": GraphOperationRoute(
        "logseq.Editor.removeProperty", None, "rejected",
        notes="logseq.cli.removeProperty returns HTTP 200 but is a no-op: the "
        "property definition is unchanged afterward (confirmed via getPageData "
        "and listProperties before/after). No working DB route to remove a "
        "property definition.",
    ),
    "upsert_block_property": GraphOperationRoute(
        "logseq.Editor.upsertBlockProperty", None, "rejected",
        notes="logseq.cli.upsertBlockProperty hangs (HTTP 0). Set the property "
        "at block-creation time via upsert_nodes instead of updating it after the fact.",
    ),
    "remove_block_property": GraphOperationRoute(
        "logseq.Editor.removeBlockProperty", None, "rejected",
        notes="logseq.cli.removeBlockProperty hangs (HTTP 0). No working DB "
        "route to remove a block property yet.",
    ),
    "add_block_tag": GraphOperationRoute(
        "logseq.Editor.addBlockTag", None, "rejected",
        notes="logseq.cli.addBlockTag hangs (HTTP 0). Tag a block at creation "
        "time via upsert_nodes's 'tags' data key (array of tag UUIDs) instead.",
    ),
    "remove_block_tag": GraphOperationRoute(
        "logseq.Editor.removeBlockTag", None, "rejected",
        notes="logseq.cli.removeBlockTag hangs (HTTP 0). No working DB route "
        "to remove a tag from a block yet.",
    ),
    "delete_page": GraphOperationRoute(
        "logseq.Editor.deletePage", "logseq.cli.deletePage", "verified",
        notes="Takes the page title/name (like Editor.deletePage). Soft-deletes "
        "(recycles) an ordinary page (sets deleted-at/deleted-by-ref); tags, "
        "properties, and today's journal delete permanently instead -- that is "
        "Logseq's own recycle-bin behavior, not something this client controls.",
    ),
    "rename_page": GraphOperationRoute(
        "logseq.Editor.renamePage", "logseq.cli.renamePage", "verified",
        notes="Takes the page's UUID as its first argument (not its title, "
        "unlike Editor.renamePage) -- LogSeq.rename_page resolves the name to "
        "a UUID via get_page_data before calling this route in DB mode.",
    ),
    "get_pages_from_namespace": GraphOperationRoute(
        "logseq.Editor.getPagesFromNamespace", "logseq.cli.getPagesFromNamespace", "rejected",
        notes="logseq.cli.getPagesFromNamespace crashes with a clean HTTP 500 "
        "(\"Cannot read properties of undefined (reading 'apply')\") — not a hang, not viable.",
    ),
    "get_pages_tree_from_namespace": GraphOperationRoute(
        "logseq.Editor.getPagesTreeFromNamespace", "logseq.cli.getPagesTreeFromNamespace", "rejected",
        notes="logseq.cli.getPagesTreeFromNamespace crashes with a clean HTTP 500 "
        "(\"Cannot read properties of undefined (reading 'apply')\") — not a hang, not viable.",
    ),
}


from .pages import PageMixin
from .blocks import BlockMixin
from .properties import PropertyMixin
from .tags import TagMixin
from .search import SearchMixin


class LogSeq(PageMixin, BlockMixin, PropertyMixin, TagMixin, SearchMixin):
    def __init__(
        self,
        api_key: str,
        protocol: str = "http",
        host: str = "127.0.0.1",
        port: int = 12315,
        verify_ssl: bool = True,
        timeout: tuple[float, float] | None = None,
        db_mode: bool = False,
    ):
        self.api_key = api_key
        self.protocol = protocol
        self.host = host
        self.port = port
        self.verify_ssl = verify_ssl
        self.db_mode = db_mode
        self.timeout = timeout or (3, 6)

        # Reuse connections while allowing concurrent MCP requests to proceed.
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=10,
            max_retries=0,
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def get_base_url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}/api"

    def _get_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    @classmethod
    def api_route_manifest(cls) -> dict[str, dict[str, str | None]]:
        """Return the graph-operation map for tests and external harnesses."""
        return {operation: asdict(route) for operation, route in GRAPH_OPERATION_ROUTES.items()}

    def _method_for(self, operation: str) -> str:
        """Resolve the HTTP method for a logical operation under a hard File/DB split.

        File graphs always call ``file_method``. DB graphs always call
        ``db_method`` when verified — never a cross-namespace fallback. An
        operation that is "rejected" or "untested" for DB graphs raises
        instead of silently using the Editor.* method.
        """
        try:
            route = GRAPH_OPERATION_ROUTES[operation]
        except KeyError as error:
            raise ValueError(f"Unknown graph operation: {operation}") from error

        if not self.db_mode:
            if route.file_method is None:
                raise RuntimeError(f"{operation} is available only for DB graphs")
            return route.file_method

        if route.db_status == "verified" and route.db_method:
            return route.db_method
        raise RuntimeError(
            f"{operation} is not available for Logseq DB graphs "
            f"(db_status={route.db_status}"
            + (f": {route.notes}" if route.notes else "")
            + ")"
        )

    def _call_api(self, method: str, args: list) -> Any:
        response = self._session.post(
            self.get_base_url(),
            headers=self._get_headers(),
            json={"method": method, "args": args},
            verify=self.verify_ssl,
            timeout=self.timeout,
        )
        self._raise_for_status_verbose(response, method)
        return response.json()

    @staticmethod
    def _raise_for_status_verbose(response: requests.Response, context: str) -> None:
        """Raise an HTTP error that retains Logseq's diagnostic response body."""
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as error:
            body = (response.text or "").strip()[:2000]
            raise RuntimeError(
                f"{context} failed ({response.status_code}): {body or '<empty response body>'}"
            ) from error

    def check_current_is_db_graph(self) -> bool:
        """Ask Logseq whether the active graph uses the DB graph format."""
        return bool(self._call_api("logseq.App.checkCurrentIsDbGraph", []))

