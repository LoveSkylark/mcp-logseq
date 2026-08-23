"""Page-level LogSeq client methods."""
import logging
import requests
from typing import Any

logger = logging.getLogger("mcp-logseq")

class PageMixin:
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

    def delete_page(self, page_name: str) -> Any:
        """Delete a LogSeq page by name."""
        url = self.get_base_url()
        logger.info(f"Deleting page '{page_name}'")

        try:
            if self.db_mode:
                # cli.deletePage (live-verified 2026-08-23) soft-deletes/recycles
                # the page (sets deleted-at/deleted-by-ref) rather than removing
                # it outright, matching Logseq's documented 30-day recycle
                # behavior for ordinary pages. Tags, properties, and today's
                # journal delete permanently instead -- that's Logseq's own
                # behavior, not something this client controls.
                response = self._session.post(
                    url,
                    headers=self._get_headers(),
                    json={
                        "method": self._method_for("delete_page"),
                        "args": [page_name],
                    },
                    verify=self.verify_ssl,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                logger.info(f"Successfully deleted page '{page_name}'")
                if response.text and response.text.strip() and response.text.strip() != 'null':
                    return response.json()
                return None

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
                json={"method": self._method_for("delete_page"), "args": [page_name]},
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
                    "method": self._method_for("create_page"),
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
            if self.db_mode:
                # cli.renamePage (live-verified 2026-08-23) takes the page's
                # UUID as its first argument, not its title.
                page_data = self.get_page_data(old_name)
                page_uuid = ((page_data or {}).get("entity") or {}).get("uuid")
                if not page_uuid:
                    raise ValueError(f"Page '{old_name}' does not exist")
                response = self._session.post(
                    url,
                    headers=self._get_headers(),
                    json={
                        "method": self._method_for("rename_page"),
                        "args": [page_uuid, new_name],
                    },
                    verify=self.verify_ssl,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                if response.text and response.text.strip() and response.text.strip() != 'null':
                    return response.json()
                return None

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
                    "method": self._method_for("rename_page"),
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

    def get_page_data(self, page_name: str, expand_children: bool = False) -> Any:
        """
        Read a DB page entity and its direct page-level blocks.

        Unlike `Editor.getPageBlocksTree` (which hangs in 2.0.1), this returns,
        but it does not guarantee a recursively nested block tree.

        Args:
            page_name: Page name or UUID.
            expand_children: When True, fan out one `get_block` call per
                top-level block to fill in each one's nested "children" tree
                (bundling the fan-out this caller would otherwise have to do
                itself, one MCP round trip per block). A block whose subtree
                is too large/slow to expand gets a "children_error" key with
                the failure instead of aborting the whole page read -- a
                single huge section should not hide the rest of the page.
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
                result = response.json()
            except ValueError:
                return response.text

            if expand_children and isinstance(result, dict):
                blocks = result.get("blocks")
                if isinstance(blocks, list):
                    for block in blocks:
                        if not isinstance(block, dict):
                            continue
                        block_uuid = block.get("uuid") or block.get("block/uuid")
                        if not block_uuid:
                            continue
                        try:
                            expanded = self.get_block(str(block_uuid), include_children=True)
                            if isinstance(expanded, dict):
                                block["children"] = expanded.get("children", [])
                        except Exception as e:
                            logger.warning(
                                f"Could not expand children for block '{block_uuid}': {e}"
                            )
                            block["children_error"] = str(e)

            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Error in get_page_data: {str(e)}")
            raise
