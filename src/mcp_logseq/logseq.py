import requests
import logging
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger("mcp-logseq")


@dataclass(frozen=True)
class GraphOperationRoute:
    """Method mapping for one logical MCP operation across graph models."""

    file_method: str | None
    db_method: str | None
    db_status: str
    db_fallback_method: str | None = None
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
    # logseq.cli.getBlock/getBlockProperties were live-tested against
    # Logseq 2.0.1 on 2026-08-23 and both hang indefinitely (curl timeout,
    # HTTP 0) regardless of includeChildren, while other cli.* calls made in
    # the same session returned normally. Rejected; retain the Editor.*
    # fallback rather than re-testing without new evidence.
    "get_block": GraphOperationRoute(
        "logseq.Editor.getBlock",
        "logseq.cli.getBlock",
        "rejected",
        db_fallback_method="logseq.Editor.getBlock",
        notes="Rejected: logseq.cli.getBlock hangs (HTTP 0, 20s timeout) for both includeChildren=true and false.",
    ),
    "get_block_properties": GraphOperationRoute(
        "logseq.Editor.getBlockProperties",
        "logseq.cli.getBlockProperties",
        "rejected",
        db_fallback_method="logseq.Editor.getBlockProperties",
        notes="Rejected: logseq.cli.getBlockProperties hangs (HTTP 0, 20s timeout) even with a bare block UUID argument.",
    ),
}


class LogSeq:
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
        """Resolve the currently enabled HTTP method for a logical operation."""
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
        if route.db_fallback_method:
            logger.warning(
                "DB route %s is %s; using fallback %s until live verification succeeds",
                operation,
                route.db_status,
                route.db_fallback_method,
            )
            return route.db_fallback_method
        raise RuntimeError(f"{operation} has no enabled DB route")

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

    def create_page(self, title: str, content: str = "") -> Any:
        """Create a new LogSeq page with specified title and content."""
        url = self.get_base_url()
        logger.info(f"Creating page '{title}'")

        try:
            # Step 1: Create the page
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.Editor.createPage",
                    "args": [title, {}, {"createFirstBlock": True}],
                },
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            page_result = response.json()

            # Step 2: Add content if provided
            if content and content.strip():
                response = self._session.post(
                    url,
                    headers=self._get_headers(),
                    json={
                        "method": "logseq.Editor.appendBlockInPage",
                        "args": [title, content],
                    },
                    verify=self.verify_ssl,
                    timeout=self.timeout,
                )
                response.raise_for_status()

            return page_result

        except Exception as e:
            logger.error(f"Error creating page: {str(e)}")
            raise

    def page_exists(self, page_name: str) -> bool:
        """Check whether a page with the given name already exists."""
        url = self.get_base_url()

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={"method": "logseq.Editor.getPage", "args": [page_name]},
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            # Treat any falsy payload (null, {}) as "missing", matching
            # get_page_content's defensive check on getPage responses.
            return bool(response.json())

        except Exception as e:
            logger.error(f"Error checking if page exists: {str(e)}")
            raise

    def list_pages(self, expand: bool = False) -> Any:
        """List all pages in the LogSeq graph."""
        url = self.get_base_url()
        logger.info("Listing pages")

        try:
            method = self._method_for("list_pages")
            args = [{"expand": expand}] if self.db_mode else []
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={"method": method, "args": args},
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            self._raise_for_status_verbose(response, method)
            result = response.json()
            if self.db_mode and isinstance(result, list):
                normalized = []
                for page in result:
                    if not isinstance(page, dict):
                        continue
                    page = dict(page)
                    title = (
                        page.get("block/title")
                        or page.get("block/name")
                        or page.get("title")
                        or page.get("name")
                    )
                    if title:
                        page.setdefault("name", title)
                        page.setdefault("originalName", title)
                    normalized.append(page)
                return normalized
            return result

        except Exception as e:
            logger.error(f"Error listing pages: {str(e)}")
            raise

    def list_tags(self, expand: bool = False) -> Any:
        """List DB graph tags through Logseq's native CLI API."""
        if not self.db_mode:
            return []
        url = self.get_base_url()
        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={"method": self._method_for("list_tags"), "args": [{"expand": expand}]},
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            self._raise_for_status_verbose(response, "logseq.cli.listTags")
            return response.json()
        except Exception as e:
            logger.error(f"Error listing tags: {str(e)}")
            raise

    def list_properties(self, expand: bool = False) -> Any:
        """List DB graph properties through Logseq's native CLI API."""
        if not self.db_mode:
            return []
        url = self.get_base_url()
        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={"method": self._method_for("list_properties"), "args": [{"expand": expand}]},
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            self._raise_for_status_verbose(response, "logseq.cli.listProperties")
            return response.json()
        except Exception as e:
            logger.error(f"Error listing properties: {str(e)}")
            raise

    def get_property(self, property_name: str) -> Any:
        return self._call_api("logseq.Editor.getProperty", [property_name])

    def upsert_property(
        self, property_name: str, schema: dict | None = None, options: dict | None = None
    ) -> Any:
        return self._call_api(
            "logseq.Editor.upsertProperty",
            [property_name, schema or {}, options or {}],
        )

    def remove_property(self, property_name: str) -> Any:
        return self._call_api("logseq.Editor.removeProperty", [property_name])

    def get_block_properties(self, block_uuid: str) -> Any:
        return self._call_api(self._method_for("get_block_properties"), [block_uuid])

    def get_block_property(self, block_uuid: str, property_name: str) -> Any:
        return self._call_api(
            "logseq.Editor.getBlockProperty", [block_uuid, property_name]
        )

    def upsert_block_property(
        self, block_uuid: str, property_name: str, value: Any, options: dict | None = None
    ) -> Any:
        return self._call_api(
            "logseq.Editor.upsertBlockProperty",
            [block_uuid, property_name, value, options or {}],
        )

    def get_tag(self, tag_name_or_ident: str) -> Any:
        return self._call_api("logseq.Editor.getTag", [tag_name_or_ident])

    def get_tags_by_name(self, tag_name: str) -> Any:
        return self._call_api("logseq.Editor.getTagsByName", [tag_name])

    def get_tag_objects(self, tag_name_or_ident: str) -> Any:
        return self._call_api("logseq.Editor.getTagObjects", [tag_name_or_ident])

    def create_tag(self, tag_name: str, options: dict | None = None) -> Any:
        return self._call_api("logseq.Editor.createTag", [tag_name, options or {}])

    def add_tag_property(self, tag_id: str, property_id_or_name: str) -> Any:
        return self._call_api(
            "logseq.Editor.addTagProperty", [tag_id, property_id_or_name]
        )

    def remove_tag_property(self, tag_id: str, property_id_or_name: str) -> Any:
        return self._call_api(
            "logseq.Editor.removeTagProperty", [tag_id, property_id_or_name]
        )

    def add_tag_extends(self, tag_id: str, parent_tag_id_or_name: str) -> Any:
        return self._call_api(
            "logseq.Editor.addTagExtends", [tag_id, parent_tag_id_or_name]
        )

    def remove_tag_extends(self, tag_id: str, parent_tag_id_or_name: str) -> Any:
        return self._call_api(
            "logseq.Editor.removeTagExtends", [tag_id, parent_tag_id_or_name]
        )

    def add_block_tag(self, block_uuid: str, tag_id: str) -> Any:
        return self._call_api("logseq.Editor.addBlockTag", [block_uuid, tag_id])

    def remove_block_tag(self, block_uuid: str, tag_id: str) -> Any:
        return self._call_api("logseq.Editor.removeBlockTag", [block_uuid, tag_id])

    def get_page_content(self, page_name: str) -> Any:
        """Get content of a LogSeq page including metadata and block content."""
        if self.db_mode:
            page_data = self.get_page_data(page_name)
            if not page_data or not isinstance(page_data, dict) or page_data.get("error"):
                return None
            return {
                "page": page_data.get("entity") or page_data.get("page") or {},
                "blocks": page_data.get("blocks") or [],
            }

        url = self.get_base_url()
        logger.info(f"Getting content for page '{page_name}'")

        try:
            # Step 1: Get page metadata (includes UUID)
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={"method": "logseq.Editor.getPage", "args": [page_name]},
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            page_info = response.json()

            if not page_info:
                logger.error(f"Page '{page_name}' not found")
                return None

            # Step 2: Get page blocks using the page name
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={"method": "logseq.Editor.getPageBlocksTree", "args": [page_name]},
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            blocks = response.json()

            # Step 3: Extract page properties from first block
            # In Logseq, page properties are stored in the first block
            properties = {}
            if blocks and len(blocks) > 0:
                properties = blocks[0].get("properties", {})

            return {
                "page": {**page_info, "properties": properties},
                "blocks": blocks or [],
            }

        except Exception as e:
            logger.error(f"Error getting page content: {str(e)}")
            raise

    def search_content(self, query: str, options: dict | None = None) -> Any:
        """Search for content across LogSeq pages and blocks."""
        url = self.get_base_url()
        logger.info(f"Searching for '{query}'")

        search_options = options or {}
        method = self._method_for("search")
        if self.db_mode and not options:
            search_options = {"enable-snippet?": False}

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={"method": method, "args": [query, search_options]},
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Error searching content: {str(e)}")
            raise

    def delete_page(self, page_name: str) -> Any:
        """Delete a LogSeq page by name."""
        if self.db_mode:
            raise ValueError(
                "delete_page is disabled for DB graphs because the Logseq API can "
                "flatten references to the deleted page. Delete the page in Logseq instead."
            )

        url = self.get_base_url()
        logger.info(f"Deleting page '{page_name}'")

        try:
            # Pre-delete validation: verify page exists
            existing_pages = self.list_pages()
            page_names = [
                p.get("originalName") or p.get("name")
                for p in existing_pages
                if p.get("originalName") or p.get("name")
            ]

            if page_name not in page_names:
                raise ValueError(f"Page '{page_name}' does not exist")

            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={"method": "logseq.Editor.deletePage", "args": [page_name]},
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Successfully deleted page '{page_name}'")
            return result

        except ValueError:
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            logger.error(f"Error deleting page '{page_name}': {str(e)}")
            raise

    # =========================================================================
    # Block-Level API Methods
    # =========================================================================

    def get_page_blocks(self, page_name: str) -> list[dict]:
        """
        Get all root-level blocks for a page.

        Args:
            page_name: Name of the page

        Returns:
            List of block entities with UUIDs
        """
        if self.db_mode:
            page_data = self.get_page_data(page_name)
            if not page_data or not isinstance(page_data, dict) or page_data.get("error"):
                return []

            def normalize_block(block: dict) -> dict:
                normalized = dict(block)
                normalized.setdefault("uuid", block.get("block/uuid"))
                normalized.setdefault("content", block.get("block/title", ""))
                children = block.get("children", block.get("block/children", [])) or []
                normalized["children"] = [
                    normalize_block(child) for child in children if isinstance(child, dict)
                ]
                return normalized

            return [
                normalize_block(block)
                for block in page_data.get("blocks", [])
                if isinstance(block, dict)
            ]

        url = self.get_base_url()
        logger.info(f"Getting blocks for page '{page_name}'")

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={"method": "logseq.Editor.getPageBlocksTree", "args": [page_name]},
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json() or []

        except Exception as e:
            logger.error(f"Error getting page blocks: {str(e)}")
            raise

    def remove_block(self, block_uuid: str) -> None:
        """
        Remove a single block by UUID.

        Args:
            block_uuid: UUID of block to remove
        """
        self.delete_block(block_uuid)

    def clear_page_content(self, page_name: str) -> None:
        """
        Remove all blocks from a page.

        Args:
            page_name: Name of the page to clear
        """
        logger.info(f"Clearing content from page '{page_name}'")

        blocks = self.get_page_blocks(page_name)
        for block in blocks:
            block_uuid = block.get("uuid")
            if block_uuid:
                self.remove_block(block_uuid)

        logger.info(f"Cleared {len(blocks)} blocks from page '{page_name}'")

    def insert_batch_block(
        self, src_block: str, blocks: list[dict], sibling: bool = True
    ) -> Any:
        """
        Insert multiple blocks with hierarchy at once.

        Uses Logseq's insertBatchBlock API to insert a tree of blocks.

        Args:
            src_block: UUID of anchor block (blocks will be inserted after this)
            blocks: List of IBatchBlock dicts with 'content', optional 'children',
                    and optional 'properties'
            sibling: If True, insert as siblings of src_block;
                     if False, insert as children

        Returns:
            List of created block entities
        """
        url = self.get_base_url()
        logger.info(f"Inserting batch of {len(blocks)} blocks")

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.Editor.insertBatchBlock",
                    "args": [src_block, blocks, {"sibling": sibling}],
                },
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Successfully inserted batch blocks")
            return result

        except Exception as e:
            logger.error(f"Error inserting batch blocks: {str(e)}")
            raise

    def append_block_in_page(
        self, page_name: str, content: str, properties: dict | None = None
    ) -> dict:
        """
        Append a single block to the end of a page.

        Args:
            page_name: Name of the page
            content: Block content
            properties: Optional block properties

        Returns:
            Created block entity
        """
        url = self.get_base_url()
        logger.debug(f"Appending block to page '{page_name}'")

        try:
            args: list[Any] = [page_name, content]
            if properties:
                args.append({"properties": properties})

            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={"method": "logseq.Editor.appendBlockInPage", "args": args},
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Error appending block to page: {str(e)}")
            raise

    def create_page_with_blocks(
        self, title: str, blocks: list[dict], properties: dict | None = None
    ) -> dict:
        """
        Create a new page and populate it with blocks.

        This is the improved version of create_page that properly handles
        block hierarchy using insertBatchBlock.

        Args:
            title: Page title
            blocks: List of IBatchBlock dicts (from parser)
            properties: Optional page properties

        Returns:
            Created page entity
        """
        url = self.get_base_url()
        logger.info(f"Creating page '{title}' with {len(blocks)} blocks")

        # Guard against duplicates at the write layer: Logseq auto-numbers
        # pages with an existing name ("Page(1)", "Page 2"), which silently
        # fragments content when a timed-out create is retried (issue #58).
        if self.page_exists(title):
            raise ValueError(f"Page '{title}' already exists")

        try:
            # Normalize properties for the createPage API.
            # Passing them as the 2nd argument stores them at the page entity level,
            # which is what Logseq queries via (page-property ...) and displays in
            # the page info panel. Using upsertBlockProperty on a content block
            # would create block-level properties instead, breaking queries.
            api_props: dict = {}
            if properties:
                for key, value in properties.items():
                    api_props[key] = self._normalize_property_value(key, value)

            # Step 1: Create the page with page-level properties
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.Editor.createPage",
                    "args": [title, api_props, {"createFirstBlock": True}],
                },
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            page_result = response.json()

            # Step 2: If we have blocks to insert, get the first block and use it as anchor
            if blocks:
                page_blocks = self.get_page_blocks(title)

                if page_blocks and len(page_blocks) > 0:
                    first_block_uuid = page_blocks[0].get("uuid")

                    if first_block_uuid:
                        # Insert all blocks as siblings after the first block
                        self.insert_batch_block(first_block_uuid, blocks, sibling=True)

                        logger.info(f"api_props={api_props!r}, will delete first block: {not api_props}")
                        if not api_props:
                            # No properties — remove the empty placeholder block
                            self.remove_block(first_block_uuid)
                        # When properties exist, keep the first block: createPage
                        # stores them there as a preBlock (tags:: val lines)
                else:
                    # Fallback: append blocks one by one if no first block
                    logger.warning("No first block found, using fallback append method")
                    for block in blocks:
                        self._append_block_recursive(title, block)

            logger.info(f"Successfully created page '{title}' with blocks")
            return page_result

        except Exception as e:
            logger.error(f"Error creating page with blocks: {str(e)}")
            raise

    def _append_block_recursive(
        self, page_name: str, block: dict, parent_uuid: str | None = None
    ) -> None:
        """
        Recursively append a block and its children to a page.

        Fallback method when insertBatchBlock is not available.
        """
        content = block.get("content", "")
        properties = block.get("properties")
        children = block.get("children", [])

        # Append this block, nested under parent if available
        if parent_uuid:
            result = self.insert_block_as_child(parent_uuid, content, properties)
        else:
            result = self.append_block_in_page(page_name, content, properties)
        block_uuid = result.get("uuid") if result else None

        # Recursively append children under this block
        for child in children:
            self._append_block_recursive(page_name, child, block_uuid)

    def update_page_with_blocks(
        self,
        page_name: str,
        blocks: list[dict],
        properties: dict | None = None,
        mode: str = "append",
    ) -> dict:
        """
        Update a page with new blocks.

        Args:
            page_name: Name of the page to update
            blocks: List of IBatchBlock dicts (from parser)
            properties: Optional page properties to set
            mode: "append" to add after existing content, "replace" to clear first

        Returns:
            Dict with update results
        """
        logger.info(
            f"Updating page '{page_name}' with {len(blocks)} blocks (mode={mode})"
        )

        # Validate page exists
        existing_pages = self.list_pages()
        page_names = [
            p.get("originalName") or p.get("name")
            for p in existing_pages
            if p.get("originalName") or p.get("name")
        ]

        if page_name not in page_names:
            raise ValueError(f"Page '{page_name}' does not exist")

        results: list[tuple[str, Any]] = []

        try:
            # Handle replace mode - clear existing content
            if mode == "replace":
                self.clear_page_content(page_name)
                results.append(("cleared", True))

            # Insert new blocks FIRST, then set properties
            if blocks:
                if mode == "replace":
                    # After clearing, we need to add a first block to use as anchor
                    first_block = blocks[0]
                    anchor = self.append_block_in_page(
                        page_name,
                        first_block.get("content", ""),
                        first_block.get("properties"),
                    )
                    anchor_uuid = anchor.get("uuid") if anchor else None

                    # Insert children of first block if any
                    if anchor_uuid and first_block.get("children"):
                        self.insert_batch_block(
                            anchor_uuid,
                            first_block["children"],
                            sibling=False,  # Insert as children
                        )

                    # Insert remaining blocks as siblings
                    if len(blocks) > 1 and anchor_uuid:
                        self.insert_batch_block(anchor_uuid, blocks[1:], sibling=True)

                    results.append(("blocks_replaced", len(blocks)))
                else:
                    # Append mode - get last block and insert after it
                    page_blocks = self.get_page_blocks(page_name)

                    if page_blocks:
                        last_block_uuid = page_blocks[-1].get("uuid")
                        if last_block_uuid:
                            self.insert_batch_block(
                                last_block_uuid, blocks, sibling=True
                            )
                            results.append(("blocks_appended", len(blocks)))
                    else:
                        # No existing blocks, just append
                        for block in blocks:
                            self._append_block_recursive(page_name, block)
                        results.append(("blocks_appended", len(blocks)))

            # Update properties AFTER blocks are inserted/replaced.
            #
            # Property storage differs by graph type:
            #   - DB graphs: properties live at the page entity level and must be
            #     written via setPageProperties; block-level properties don't
            #     register as page properties (invisible to (page-property ...)
            #     queries and the page info panel).
            #   - File graphs: page properties are the `key:: value` lines in the
            #     first block, so upsertBlockProperty on that block is the native
            #     representation and updates values in place.
            if properties:
                if mode == "append":
                    existing_props = self._get_page_level_properties(page_name)
                    merged_props = {**existing_props, **properties}
                    if self.db_mode:
                        self._set_page_level_properties(page_name, merged_props)
                    else:
                        self._update_page_properties(page_name, properties)
                    results.append(("properties", merged_props))
                else:
                    # Replace mode - drop existing properties, set only the new ones
                    if self.db_mode:
                        self._set_page_level_properties(page_name, properties)
                    else:
                        self._replace_page_properties(page_name, properties)
                    results.append(("properties", properties))

            return {"updates": results, "page": page_name}

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error updating page with blocks: {str(e)}")
            raise

    def _get_page_properties(self, page_name: str) -> dict:
        """
        Get current page properties from the first block.

        Returns:
            Dict of current page properties, or empty dict if none found
        """
        page_blocks = self.get_page_blocks(page_name)
        if not page_blocks:
            return {}

        first_block = page_blocks[0]
        return first_block.get("properties", {})

    def _normalize_property_value(self, key: str, value: Any) -> Any:
        """
        Normalize property values for Logseq's upsertBlockProperty API.

        Handles special cases:
        - tags/aliases as dict with boolean values -> convert to array of keys
        - Other dicts remain as-is (for nested properties)

        Args:
            key: Property name
            value: Property value

        Returns:
            Normalized value suitable for Logseq
        """
        # Special handling for tags and aliases - convert dict to array
        if key in ("tags", "alias", "aliases") and isinstance(value, dict):
            # Extract keys where value is truthy (typically true for tags)
            return [k for k, v in value.items() if v]

        return value

    def _get_page_level_properties(self, page_name: str) -> dict:
        """
        Get page-level properties from the page entity (not from the first block).

        Uses getPage which returns the page entity with its page-level properties.
        """
        url = self.get_base_url()
        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={"method": "logseq.Editor.getPage", "args": [page_name]},
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            page = response.json()
            if page and isinstance(page, dict):
                return page.get("properties", {}) or {}
            return {}
        except Exception as e:
            logger.warning(f"Could not get page-level properties for '{page_name}': {e}")
            return {}

    def _set_page_level_properties(self, page_name: str, properties: dict) -> None:
        """
        Set page-level properties via the setPageProperties API.

        Unlike upsertBlockProperty (which sets block-level properties), this
        stores properties at the page entity level, making them visible in the
        page info panel and queryable via (page-property ...).
        """
        url = self.get_base_url()
        api_props = {
            k: self._normalize_property_value(k, v) for k, v in properties.items()
        }
        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.Editor.setPageProperties",
                    "args": [page_name, api_props],
                },
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            logger.info(f"Set {len(properties)} page-level properties on '{page_name}'")
        except Exception as e:
            logger.error(f"Could not set page-level properties for '{page_name}': {e}")
            raise

    def _resolve_first_block(self, page_name: str) -> dict:
        """
        Return the page's first block, creating an empty anchor block if none exists.

        On file graphs, page properties live in the first block. A properties-only
        update (no content) — especially in replace mode, which clears existing
        blocks first — can leave the page with no block to write to. In that case
        we create an empty anchor block, which is exactly how Logseq represents
        page properties on a fresh page (the page-properties pre-block).

        Raises:
            RuntimeError: if no block exists and an anchor could not be created,
                so the caller never reports a write that didn't happen.
        """
        page_blocks = self.get_page_blocks(page_name)
        if page_blocks and page_blocks[0].get("uuid"):
            return page_blocks[0]

        anchor = self.append_block_in_page(page_name, "")
        if anchor and anchor.get("uuid"):
            return anchor

        raise RuntimeError(
            f"Could not resolve or create a first block on page '{page_name}' "
            f"to store properties"
        )

    def _update_page_properties(self, page_name: str, properties: dict) -> None:
        """
        Update page properties by setting them on the first block.

        In Logseq, page properties are stored in the first block of the page
        using the `property:: value` syntax. This method updates properties
        by calling upsertBlockProperty on the first block.
        """
        first_block_uuid = self._resolve_first_block(page_name)["uuid"]

        # Set each property using upsertBlockProperty. Keys not listed here are
        # left untouched, which gives append-mode its merge semantics natively.
        for key, value in properties.items():
            normalized_value = self._normalize_property_value(key, value)
            self._upsert_block_property(first_block_uuid, key, normalized_value)

        logger.info(f"Updated {len(properties)} properties on page '{page_name}'")

    def _replace_page_properties(self, page_name: str, properties: dict) -> None:
        """
        Replace all page properties on the first block.

        Unlike _update_page_properties (which only upserts the supplied keys),
        this removes any existing first-block properties that are not in the new
        set, then upserts the new ones. This preserves replace-mode semantics for
        file graphs.
        """
        first_block = self._resolve_first_block(page_name)
        first_block_uuid = first_block["uuid"]

        # Remove existing properties that are not part of the new set
        existing_props = first_block.get("properties", {}) or {}
        new_keys = set(properties.keys())
        for key in existing_props:
            if key not in new_keys:
                self._remove_block_property(first_block_uuid, key)

        # Upsert the new properties
        for key, value in properties.items():
            normalized_value = self._normalize_property_value(key, value)
            self._upsert_block_property(first_block_uuid, key, normalized_value)

        logger.info(f"Replaced properties on page '{page_name}' with {len(properties)} keys")

    def _remove_block_property(self, block_uuid: str, key: str) -> None:
        """
        Remove a property from a block using Logseq's removeBlockProperty API.

        Args:
            block_uuid: UUID of the block to update
            key: Property key to remove
        """
        url = self.get_base_url()

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.Editor.removeBlockProperty",
                    "args": [block_uuid, key],
                },
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to remove property '{key}' on block {block_uuid}: {e}")
            raise

    def _upsert_block_property(self, block_uuid: str, key: str, value: Any) -> None:
        """
        Set a property on a block using Logseq's upsertBlockProperty API.

        Args:
            block_uuid: UUID of the block to update
            key: Property key
            value: Property value
        """
        url = self.get_base_url()

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.Editor.upsertBlockProperty",
                    "args": [block_uuid, key, value],
                },
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to set property '{key}' on block {block_uuid}: {e}")
            raise

    # =========================================================================
    # DB-mode Property Methods (Datascript)
    # =========================================================================

    def datascript_query(self, query: str) -> list[list]:
        """Execute a raw Datascript query against the Logseq database.

        Args:
            query: Datalog query string (e.g. '[:find ?a ?v :where [101 ?a ?v]]')

        Returns:
            List of result tuples, e.g. [["title", "My Page"], [":db/ident", ":logseq..."]]
            Each inner list corresponds to the :find clause bindings.
        """
        url = self.get_base_url()
        logger.debug(f"Executing datascript query")

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.DB.datascriptQuery",
                    "args": [query],
                },
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error executing datascript query: {str(e)}")
            raise

    def get_block_db_properties(self, block_id: int) -> dict[str, str]:
        """Get DB-mode class properties for a block.

        In Logseq DB-mode, class properties are stored as :user.property/*
        attributes on the block entity, with values referencing other entities.

        Args:
            block_id: The numeric ID of the block

        Returns:
            Dict of {property_title: value_title}
        """
        # Get all attributes and their values for this block
        query = f'[:find ?a ?v :where [{block_id} ?a ?v]]'
        try:
            attrs = self.datascript_query(query)
        except Exception:
            return {}

        user_props = {}
        for attr, val in attrs:
            if isinstance(attr, str) and attr.startswith(":user.property/"):
                user_props[attr] = val

        if not user_props:
            return {}

        # Resolve property display names and value titles
        result = {}
        for ident, val_id in user_props.items():
            # Get property display name via :db/ident lookup
            prop_name = self._resolve_entity_title_by_ident(ident) or ident

            # Get value title (val_id is an entity reference in DB-mode)
            if isinstance(val_id, int):
                val_title = self._resolve_entity_title(val_id) or str(val_id)
            else:
                val_title = str(val_id)

            result[prop_name] = val_title

        return result

    def _resolve_entity_title_by_ident(self, ident: str) -> str | None:
        """Resolve a :db/ident to its entity's title."""
        query = f'[:find ?id :where [?id :db/ident {ident}]]'
        try:
            result = self.datascript_query(query)
            if result:
                return self._resolve_entity_title(result[0][0])
        except Exception:
            pass
        return None

    def _resolve_entity_title(self, entity_id: int) -> str | None:
        """Get the title of an entity by its numeric ID."""
        query = f'[:find ?a ?v :where [{entity_id} ?a ?v]]'
        try:
            attrs = self.datascript_query(query)
            for attr, val in attrs:
                if attr == "title":
                    return str(val)
        except Exception:
            pass
        return None

    def _resolve_idents_batch(self, idents: set[str]) -> dict[str, int]:
        """Resolve multiple :db/ident values to their entity IDs in one query.

        Args:
            idents: Set of ident strings (e.g. {":user.property/status-abc"})

        Returns:
            Dict of {ident: entity_id}
        """
        if not idents:
            return {}
        or_clauses = " ".join(f'[?id :db/ident {ident}]' for ident in idents)
        query = f'[:find ?id ?ident :where (or {or_clauses}) [?id :db/ident ?ident]]'
        try:
            result = self.datascript_query(query)
            return {ident: eid for eid, ident in result if isinstance(ident, str)}
        except Exception:
            logger.warning("Batch ident resolution failed, falling back to individual queries")
            # Fallback: resolve one by one
            mapping = {}
            for ident in idents:
                try:
                    r = self.datascript_query(f'[:find ?id :where [?id :db/ident {ident}]]')
                    if r:
                        mapping[ident] = r[0][0]
                except Exception:
                    pass
            return mapping

    def _resolve_titles_batch(self, entity_ids: set[int]) -> dict[int, str]:
        """Resolve titles for multiple entities in a single query.

        Args:
            entity_ids: Set of numeric entity IDs

        Returns:
            Dict of {entity_id: title}
        """
        if not entity_ids:
            return {}
        or_clauses = " ".join(f'[{eid} ?a ?v]' for eid in entity_ids)
        query = f'[:find ?eid ?a ?v :where (or {or_clauses})]'
        try:
            results = self.datascript_query(query)
            titles = {}
            for eid, attr, val in results:
                if attr == "title":
                    titles[eid] = str(val)
            return titles
        except Exception:
            logger.warning("Batch title resolution failed, falling back to individual queries")
            # Fallback: resolve one by one
            titles = {}
            for eid in entity_ids:
                title = self._resolve_entity_title(eid)
                if title:
                    titles[eid] = title
            return titles

    def get_blocks_db_properties(self, blocks: list[dict]) -> dict[str, dict[str, str]]:
        """Get DB-mode properties for a list of blocks (from getPageBlocksTree).

        Batched approach to minimize API round-trips:
        1. Per block: query attributes (1 call per block)
        2. Batch resolve all :user.property/* idents to entity IDs (1 call)
        3. Batch resolve all entity titles (property names + values) (1 call)

        Args:
            blocks: List of block dicts from getPageBlocksTree

        Returns:
            Dict of {block_uuid: {property_title: value_title}}
        """
        # Phase 1: collect all block attributes (1 query per block)
        block_props: dict[str, dict[str, Any]] = {}  # uuid -> {ident: val}

        def collect_attrs(block_list: list[dict]) -> None:
            for block in block_list:
                block_id = block.get("id")
                block_uuid = str(block.get("uuid", ""))
                if block_id and block_uuid:
                    query = f'[:find ?a ?v :where [{block_id} ?a ?v]]'
                    try:
                        attrs = self.datascript_query(query)
                    except Exception:
                        attrs = []
                    user_props = {}
                    for attr, val in attrs:
                        if isinstance(attr, str) and attr.startswith(":user.property/"):
                            user_props[attr] = val
                    if user_props:
                        block_props[block_uuid] = user_props
                collect_attrs(block.get("children", []))

        collect_attrs(blocks)

        if not block_props:
            return {}

        # Phase 2: batch resolve all unique idents to entity IDs (1 query)
        all_idents = set()
        for props in block_props.values():
            all_idents.update(props.keys())

        ident_to_eid = self._resolve_idents_batch(all_idents)

        # Phase 3: collect all entity IDs needing title resolution
        entity_ids_to_resolve = set(ident_to_eid.values())
        for props in block_props.values():
            for val in props.values():
                if isinstance(val, int):
                    entity_ids_to_resolve.add(val)

        # Batch resolve all titles (1 query)
        titles = self._resolve_titles_batch(entity_ids_to_resolve)

        # Phase 4: assemble results using the resolved titles
        result = {}
        for block_uuid, props in block_props.items():
            resolved = {}
            for ident, val in props.items():
                # Property name: ident -> entity ID -> title
                prop_eid = ident_to_eid.get(ident)
                prop_name = titles.get(prop_eid) if prop_eid else None
                prop_name = prop_name or ident

                # Value: entity ref -> title, or string as-is
                if isinstance(val, int):
                    val_title = titles.get(val) or str(val)
                else:
                    val_title = str(val)

                resolved[prop_name] = val_title
            if resolved:
                result[block_uuid] = resolved

        return result

    def resolve_property_ident(self, property_name: str) -> str | None:
        """Look up a DB property ident for a display name or return a full ident.

        Uses a two-step approach since DB-mode datascript queries cannot filter
        on string attributes directly.

        Args:
            property_name: The human-readable property name (e.g. "Content status")

        Returns:
            The ident string (e.g. ":logseq.property/status") or None
        """
        if property_name.startswith(":"):
            return property_name

        property_ident_prefixes = (
            ":user.property/",
            ":logseq.property/",
            ":plugin.property.",
        )
        # Get all user property entities
        query = '[:find ?id ?ident :where [?id :db/ident ?ident]]'
        result = self.datascript_query(query)
        for entity_id, ident in result:
            if isinstance(ident, str) and ident.startswith(property_ident_prefixes):
                title = self._resolve_entity_title(entity_id)
                if title and title.lower() == property_name.lower():
                    return ident
        return None

    def get_block(self, block_uuid: str, include_children: bool = True) -> Any:
        """Get a LogSeq block by UUID, optionally including its children tree.

        Args:
            block_uuid: UUID of the block to retrieve.
            include_children: Whether to include nested children (default True).

        Returns:
            Block dict with content, properties, uuid, children, etc.
        """
        url = self.get_base_url()
        if self.db_mode and not include_children:
            logger.warning(
                "Logseq DB graphs hang on Editor.getBlock with includeChildren=false; "
                "including children instead"
            )
            include_children = True
        logger.info(f"Getting block '{block_uuid}' (children={include_children})")

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": self._method_for("get_block"),
                    "args": [block_uuid, {"includeChildren": include_children}],
                },
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()

            if result is None:
                raise ValueError(f"Block '{block_uuid}' not found")

            logger.info(f"Successfully retrieved block '{block_uuid}'")
            return result

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error getting block '{block_uuid}': {str(e)}")
            raise

    def get_block_from_page_data(self, page_name: str, block_uuid: str) -> Any:
        """Read a DB page and return a top-level block by UUID."""
        page_data = self.get_page_data(page_name)
        if not isinstance(page_data, dict) or page_data.get("error"):
            raise ValueError(f"Page '{page_name}' not found")

        def find_block(blocks: list[Any]) -> dict | None:
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                candidate_uuid = str(block.get("uuid") or block.get("block/uuid") or "")
                if candidate_uuid == block_uuid:
                    return block
            return None

        block = find_block(page_data.get("blocks") or [])
        if block is None:
            raise ValueError(f"Block '{block_uuid}' not found on page '{page_name}'")
        return block

    def _get_page_name_by_id(self, page_id) -> str | None:
        """Resolve a page's human-readable name from its db id (or uuid)."""
        url = self.get_base_url()
        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={"method": "logseq.Editor.getPage", "args": [page_id]},
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            page = response.json()
            if page and isinstance(page, dict):
                return page.get("originalName") or page.get("name")
        except Exception as e:
            logger.warning(f"Could not resolve page name for id '{page_id}': {e}")
        return None

    def get_block_page_name(self, block_uuid: str) -> str | None:
        """Resolve the name of the page that owns a given block.

        Returns None if the page cannot be determined.
        """
        try:
            block = self.get_block(block_uuid, include_children=False)
        except Exception as e:
            logger.warning(f"Could not fetch block '{block_uuid}' for page resolution: {e}")
            return None
        if not block or not isinstance(block, dict):
            return None
        page_ref = block.get("page")
        if isinstance(page_ref, dict):
            name = page_ref.get("originalName") or page_ref.get("name")
            if name:
                return name
            page_id = page_ref.get("id")
            if page_id is not None:
                return self._get_page_name_by_id(page_id)
        return None

    def resolve_page_uuids(self, uuids: list[str]) -> dict[str, str]:
        """Resolve a list of page UUIDs to their human-readable names.

        Batch-resolves by calling logseq.Editor.getPage once per unique UUID.
        Results are returned as a dict mapping UUID -> page name.
        UUIDs that cannot be resolved are silently omitted.

        Args:
            uuids: List of page UUID strings to resolve.

        Returns:
            Dict mapping UUID string to page name string.
        """
        url = self.get_base_url()
        resolved = {}

        for uuid in set(uuids):
            try:
                response = self._session.post(
                    url,
                    headers=self._get_headers(),
                    json={"method": "logseq.Editor.getPage", "args": [uuid]},
                    verify=self.verify_ssl,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                page = response.json()

                if page and isinstance(page, dict):
                    name = page.get("originalName") or page.get("name")
                    if name:
                        resolved[uuid] = name
            except Exception as e:
                logger.warning(f"Could not resolve page UUID '{uuid}': {e}")

        logger.info(f"Resolved {len(resolved)}/{len(set(uuids))} page UUIDs")
        return resolved

    def delete_block(self, block_uuid: str) -> Any:
        """Delete a LogSeq block by UUID."""
        url = self.get_base_url()
        logger.info(f"Deleting block '{block_uuid}'")

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.Editor.removeBlock",
                    "args": [block_uuid]
                },
                verify=self.verify_ssl,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Successfully deleted block '{block_uuid}'")
            return result

        except Exception as e:
            logger.error(f"Error deleting block '{block_uuid}': {str(e)}")
            raise

    def update_block(self, block_uuid: str, content: str) -> Any:
        """Update a LogSeq block's content by UUID."""
        url = self.get_base_url()
        logger.info(f"Updating block '{block_uuid}'")

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.Editor.updateBlock",
                    "args": [block_uuid, content]
                },
                verify=self.verify_ssl,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Successfully updated block '{block_uuid}'")
            return result

        except Exception as e:
            logger.error(f"Error updating block '{block_uuid}': {str(e)}")
            raise

    def query_dsl(self, query: str) -> Any:
        """Execute a Logseq DSL query to search pages and blocks.

        Args:
            query: Logseq DSL query string (e.g., '(page-property status active)')

        Returns:
            List of matching pages/blocks from the query
        """
        url = self.get_base_url()
        logger.info(f"Executing DSL query: {query}")

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.DB.q",
                    "args": [query]
                },
                verify=self.verify_ssl,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Error executing DSL query: {str(e)}")
            raise

    def get_pages_from_namespace(self, namespace: str) -> Any:
        """Get all pages within a namespace (flat list)."""
        url = self.get_base_url()
        logger.info(f"Getting pages from namespace '{namespace}'")

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.Editor.getPagesFromNamespace",
                    "args": [namespace]
                },
                verify=self.verify_ssl,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Error getting pages from namespace: {str(e)}")
            raise

    def get_pages_tree_from_namespace(self, namespace: str) -> Any:
        """Get pages within a namespace as a tree structure."""
        url = self.get_base_url()
        logger.info(f"Getting pages tree from namespace '{namespace}'")

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.Editor.getPagesTreeFromNamespace",
                    "args": [namespace]
                },
                verify=self.verify_ssl,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Error getting pages tree from namespace: {str(e)}")
            raise

    def rename_page(self, old_name: str, new_name: str) -> Any:
        """Rename a page and update all references."""
        url = self.get_base_url()
        logger.info(f"Renaming page '{old_name}' to '{new_name}'")

        try:
            # Validate old page exists
            existing_pages = self.list_pages()
            page_names = [p.get("originalName") or p.get("name") for p in existing_pages]

            if old_name not in page_names:
                raise ValueError(f"Page '{old_name}' does not exist")

            if new_name in page_names:
                raise ValueError(f"Page '{new_name}' already exists")

            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.Editor.renamePage",
                    "args": [old_name, new_name]
                },
                verify=self.verify_ssl,
                timeout=self.timeout
            )
            response.raise_for_status()
            # renamePage returns null on success
            if response.text and response.text.strip() and response.text.strip() != 'null':
                return response.json()
            return None

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error renaming page: {str(e)}")
            raise

    def get_page_linked_references(self, page_name: str) -> Any:
        """Get all pages and blocks that reference this page (backlinks)."""
        url = self.get_base_url()
        logger.info(f"Getting backlinks for page '{page_name}'")

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.Editor.getPageLinkedReferences",
                    "args": [page_name]
                },
                verify=self.verify_ssl,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Error getting backlinks: {str(e)}")
            raise

    def insert_block_as_child(
        self,
        parent_block_uuid: str,
        content: str,
        properties: dict = None,
        sibling: bool = False
    ) -> Any:
        """Insert a new block as a child of an existing block, enabling nested block structures."""
        url = self.get_base_url()
        logger.info(f"Inserting block as {'sibling' if sibling else 'child'} of {parent_block_uuid}")

        try:
            options = {
                "sibling": sibling
            }

            if properties:
                options["properties"] = properties

            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": "logseq.Editor.insertBlock",
                    "args": [parent_block_uuid, content, options]
                },
                verify=self.verify_ssl,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()

            logger.info(f"Successfully inserted block under {parent_block_uuid}")
            return result

        except Exception as e:
            logger.error(f"Error inserting nested block: {str(e)}")
            raise

    def upsert_nodes(self, operations: list, dry_run: bool = False) -> str:
        """
        Batch create/edit nodes via Logseq's CLI API surface.

        This is `logseq.cli.upsertNodes` — a DIFFERENT write path from
        `logseq.Editor.*`. It takes many operations in a single HTTP call,
        which sidesteps the per-call write ceiling that wedges Editor writes.

        Each operation is a dict:
            {"operation": "add"|"edit",
             "entityType": "block"|"page"|"tag"|"property",
             "id": "<uuid>",            # required for edit
             "data": {"title": "..."}}  # block/page content

        Returns Logseq's summary string, e.g. "Edited: {:block 2}."
        """
        url = self.get_base_url()

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": self._method_for("upsert_nodes"),
                    "args": [operations, {"dry-run": bool(dry_run)}],
                },
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            self._raise_for_status_verbose(response, self._method_for("upsert_nodes"))
            try:
                return response.json()
            except ValueError:
                return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"Error in upsert_nodes: {str(e)}")
            raise

    def get_page_data(self, page_name: str) -> Any:
        """
        Read a DB page entity and its direct page-level blocks.

        Unlike `Editor.getPageBlocksTree` (which hangs in 2.0.1), this returns,
        but it does not guarantee a recursively nested block tree.
        """
        url = self.get_base_url()

        try:
            response = self._session.post(
                url,
                headers=self._get_headers(),
                json={
                    "method": self._method_for("get_page_data"),
                    "args": [page_name],
                },
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            self._raise_for_status_verbose(response, self._method_for("get_page_data"))
            try:
                return response.json()
            except ValueError:
                return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"Error in get_page_data: {str(e)}")
            raise
