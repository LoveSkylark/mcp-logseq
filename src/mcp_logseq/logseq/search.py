"""Search, DSL query, and DB batch write LogSeq client methods."""
import logging
import requests
from typing import Any

logger = logging.getLogger("mcp-logseq")

class SearchMixin:
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

