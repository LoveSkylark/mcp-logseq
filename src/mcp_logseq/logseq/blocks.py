"""Block-level LogSeq client methods."""
import logging
from typing import Any

logger = logging.getLogger("mcp-logseq")

class BlockMixin:
    def remove_block(self, block_uuid: str) -> None:
        """
        Remove a single block by UUID.

        Args:
            block_uuid: UUID of block to remove
        """
        self.delete_block(block_uuid)

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

    def get_block(self, block_uuid: str, include_children: bool = True) -> Any:
        """Get a LogSeq block by UUID, optionally including its children tree.

        Args:
            block_uuid: UUID of the block to retrieve.
            include_children: Whether to include nested children (default True).

        Returns:
            Block dict with content, properties, uuid, children, etc.
        """
        url = self.get_base_url()
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
        """Read a DB page's direct child blocks and return one by UUID.

        get_page_data only returns the page's direct children (a documented
        Logseq API limitation, not a bug here) -- a deeper-nested block will
        not be present and this raises.
        """
        page_data = self.get_page_data(page_name)
        if not isinstance(page_data, dict) or page_data.get("error"):
            raise ValueError(f"Page '{page_name}' not found")

        for block in page_data.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            candidate_uuid = str(block.get("uuid") or block.get("block/uuid") or "")
            if candidate_uuid == block_uuid:
                return block

        raise ValueError(
            f"Block '{block_uuid}' not found among page '{page_name}''s direct "
            "children (get_page_data cannot see deeper-nested blocks)"
        )

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
                    "method": self._method_for("delete_block"),
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
                    "method": self._method_for("update_block"),
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
                    "method": self._method_for("insert_block"),
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

