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
        "logseq.Editor.getBlock", "logseq.cli.getBlock", "verified",
        notes="Live-tested 2026-08-23: hung repeatedly in a session with prior "
        "failed Editor.* write attempts, but succeeded instantly on a fresh "
        "Logseq restart -- see the wedge-recovery note in delete_block.",
    ),
    "get_block_properties": GraphOperationRoute(
        "logseq.Editor.getBlockProperties", "logseq.cli.getBlockProperties", "verified",
        notes="Live-tested 2026-08-23: hung repeatedly alongside get_block, but "
        "succeeded instantly on a fresh Logseq restart.",
    ),
    "get_block_property": GraphOperationRoute(
        "logseq.Editor.getBlockProperty", "logseq.cli.getBlockProperty", "verified",
        notes="Live-tested 2026-08-23: hung repeatedly alongside get_block, but "
        "succeeded instantly on a fresh Logseq restart.",
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
        "logseq.Editor.updateBlock", "logseq.cli.updateBlock", "verified",
        notes="Live-tested 2026-08-23: hung in an earlier, already-wedged Editor.* "
        "write session, but succeeded instantly (and actually changed the block's "
        "content) on a fresh Logseq restart.",
    ),
    "create_page": GraphOperationRoute(
        "logseq.Editor.createPage", "logseq.cli.createPage", "rejected",
        notes="logseq.cli.createPage hangs (HTTP 0) even for a brand-new page.",
    ),
    "upsert_property": GraphOperationRoute(
        "logseq.Editor.upsertProperty", "logseq.cli.upsertProperty", "verified",
        notes="Live-tested 2026-08-23: the original 'Plugins can only upsert its own "
        "properties' HTTP 500 was a misdiagnosis -- it came from an invalid schema "
        "arg (type must be one of :date/:number/:checkbox/:default/:string/:node/"
        ":url/:datetime/:json/:asset, not free text). With a valid schema this "
        "creates the property successfully, though -- like Editor.upsertProperty/"
        "createTag -- it mints a new ':plugin.property._test_plugin/*' ident from "
        "a bare display name rather than editing an existing differently-namespaced "
        "property; that part is Logseq's plugin-ownership model, not a bug here.",
    ),
    # Not yet live-tested against a cli.* candidate. Unavailable on DB graphs
    # until verified — no fallback to Editor.* under the hard File/DB split.
    # Live-tested against Logseq 2.0.1 on 2026-08-23 (second pass, the
    # previously-"untested" operations): each cli.* candidate below was
    # bracketed with a cli.listPages responsiveness check immediately after
    # every hang, ruling out a global wedge masking a per-method issue.
    "delete_block": GraphOperationRoute(
        "logseq.Editor.removeBlock", "logseq.cli.removeBlock", "verified",
        notes="Live-tested 2026-08-23: both Editor.removeBlock and cli.removeBlock "
        "hung repeatedly in a session that had already made several failed "
        "Editor.* write attempts, but both succeeded instantly on a fresh "
        "Logseq restart. The earlier 'rejected' classification was a false "
        "negative from testing an already-wedged Editor.* write path, not a "
        "real limitation of this route -- see the wedge-recovery note below.",
    ),
    "insert_block": GraphOperationRoute(
        "logseq.Editor.insertBlock", "logseq.cli.insertBlock", "verified",
        notes="Live-tested 2026-08-23: hung in an earlier, already-wedged Editor.* "
        "write session, but succeeded instantly on a fresh Logseq restart, "
        "returning the newly-created child block entity.",
    ),
    "remove_property": GraphOperationRoute(
        "logseq.Editor.removeProperty", "logseq.cli.removeProperty", "verified",
        notes="Live-tested 2026-08-23: an earlier test found this a no-op (property "
        "unchanged after the call); re-tested on a fresh property and it actually "
        "deleted the property entity (confirmed absent from both getPageData and "
        "listProperties afterward). The earlier no-op reading does not reproduce; "
        "treat it as resolved rather than a real limitation.",
    ),
    "upsert_block_property": GraphOperationRoute(
        "logseq.Editor.upsertBlockProperty", "logseq.cli.upsertBlockProperty", "verified",
        notes="Live-tested 2026-08-23: hung in an earlier, already-wedged Editor.* "
        "write session, but succeeded instantly on a fresh Logseq restart, "
        "confirmed by reading the property back afterward.",
    ),
    "remove_block_property": GraphOperationRoute(
        "logseq.Editor.removeBlockProperty", "logseq.cli.removeBlockProperty", "verified",
        notes="Live-tested 2026-08-23: hung in an earlier, already-wedged Editor.* "
        "write session, but succeeded instantly on a fresh Logseq restart, "
        "confirmed by reading the property back afterward.",
    ),
    "add_block_tag": GraphOperationRoute(
        "logseq.Editor.addBlockTag", "logseq.cli.addBlockTag", "verified",
        notes="Live-tested 2026-08-23: hung in an earlier, already-wedged Editor.* "
        "write session, but succeeded instantly on a fresh Logseq restart, "
        "confirmed by reading the block's tags back afterward.",
    ),
    "remove_block_tag": GraphOperationRoute(
        "logseq.Editor.removeBlockTag", "logseq.cli.removeBlockTag", "verified",
        notes="Live-tested 2026-08-23: hung in an earlier, already-wedged Editor.* "
        "write session, but succeeded instantly on a fresh Logseq restart, "
        "confirmed by reading the block's tags back afterward.",
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

