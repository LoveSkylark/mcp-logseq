"""DB property + datascript LogSeq client methods."""
import logging
from typing import Any

logger = logging.getLogger("mcp-logseq")

class PropertyMixin:
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
        if self.db_mode:
            property_name = self.resolve_property_ident(property_name) or property_name
        return self._call_api(self._method_for("get_property"), [property_name])

    def upsert_property(
        self, property_name: str, schema: dict | None = None, options: dict | None = None
    ) -> Any:
        if self.db_mode:
            property_name = self.resolve_property_ident(property_name) or property_name
        return self._call_api(
            self._method_for("upsert_property"),
            [property_name, schema or {}, options or {}],
        )

    def remove_property(self, property_name: str) -> Any:
        if self.db_mode:
            property_name = self.resolve_property_ident(property_name) or property_name
        return self._call_api(self._method_for("remove_property"), [property_name])

    def get_block_properties(self, block_uuid: str) -> Any:
        return self._call_api(self._method_for("get_block_properties"), [block_uuid])

    def get_block_property(self, block_uuid: str, property_name: str) -> Any:
        if self.db_mode:
            property_name = self.resolve_property_ident(property_name) or property_name
        return self._call_api(
            self._method_for("get_block_property"), [block_uuid, property_name]
        )

    def remove_block_property(self, block_uuid: str, property_name: str) -> Any:
        if self.db_mode:
            property_name = self.resolve_property_ident(property_name) or property_name
        return self._call_api(
            self._method_for("remove_block_property"), [block_uuid, property_name]
        )

    def upsert_block_property(
        self, block_uuid: str, property_name: str, value: Any, options: dict | None = None
    ) -> Any:
        # A bare display name mints a junk :plugin.property.*/<name> ident
        # instead of resolving to the real property (live-tested on 2.0.1).
        if self.db_mode:
            property_name = self.resolve_property_ident(property_name) or property_name
        return self._call_api(
            self._method_for("upsert_block_property"),
            [block_uuid, property_name, value, options or {}],
        )

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
                    "method": self._method_for("remove_block_property"),
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
                    "method": self._method_for("upsert_block_property"),
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
        # Live-confirmed: a bare/unqualified ident (e.g. :alias, :tags) never
        # matches as a literal query value here even though the same value
        # resolves fine in the forward direction ([eid :db/ident ?v]) -- only
        # namespaced idents (:user.property/*, :logseq.property/*) match.
        # Skip them; get_blocks_db_properties falls back to _BUILTIN_IDENT_TITLES.
        namespaced_idents = {ident for ident in idents if "/" in ident}
        if not namespaced_idents:
            return {}
        or_clauses = " ".join(f'[?id :db/ident {ident}]' for ident in namespaced_idents)
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
        # Live-confirmed bug fix: `[{eid} ?a ?v]` never binds ?eid (it's a
        # literal entity id, not a var), so the old query always errored with
        # "Query for unknown vars: [?eid]" and silently fell through to the
        # N-query fallback below on every call. Ground each eid to ?eid via
        # `identity` so it actually binds and the batch query itself works.
        or_clauses = " ".join(
            f'(and [(identity {eid}) ?eid] [?eid ?a ?v])' for eid in entity_ids
        )
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

    # Structural/bookkeeping attributes every node entity carries that are
    # never themselves a user-visible property. Datascript prints unqualified
    # keywords (e.g. :tags, :alias) without their leading colon, so these are
    # bare on purpose -- see the colon-normalization below for why that
    # matters for property idents too.
    _NON_PROPERTY_BLOCK_ATTRS = frozenset({
        "uuid", "title", "name", "created-at", "updated-at", "tx-id", "order",
        "parent", "page", "refs", "tags", "level", "collapsed?", "index",
        ":logseq.property/created-by-ref",
        ":logseq.property/created-from-property",
    })

    # Display names for common built-in bare idents, since :db/ident reverse
    # lookups can't resolve them (see _resolve_idents_batch).
    _BUILTIN_IDENT_TITLES = {
        "alias": "Alias", "status": "Status", "priority": "Priority",
        "deadline": "Deadline", "scheduled": "Scheduled", "icon": "Icon",
    }

    def get_blocks_db_properties(self, blocks: list[dict]) -> dict[str, dict[str, str]]:
        """Get DB-mode properties for a list of blocks (from getPageBlocksTree).

        Batched approach to minimize API round-trips:
        1. Per block: query attributes (1 call per block)
        2. Batch resolve all property idents to entity IDs (1 call)
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
                        if not isinstance(attr, str) or attr in self._NON_PROPERTY_BLOCK_ATTRS:
                            continue
                        # Built-in properties (e.g. "alias") print as a bare
                        # keyword with no colon; namespaced idents (e.g.
                        # ":user.property/Foo-xyz", ":logseq.property/status")
                        # already have one. Normalize so both forms resolve
                        # the same way via :db/ident lookups below.
                        ident = attr if attr.startswith(":") else f":{attr}"
                        user_props[ident] = val
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
                # Property name: ident -> entity ID -> title, falling back to
                # the built-in display name map for bare idents (:alias etc.)
                # that _resolve_idents_batch can never look up, then the raw
                # ident as a last resort.
                prop_eid = ident_to_eid.get(ident)
                prop_name = titles.get(prop_eid) if prop_eid else None
                prop_name = prop_name or self._BUILTIN_IDENT_TITLES.get(ident.lstrip(":")) or ident

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
        # Single joined query for (ident, title) pairs — the previous version
        # queried idents then resolved each entity's title in a SEPARATE
        # round trip (N+1), which is slow enough on a real graph (hundreds of
        # :db/ident entities) to fail to resolve built-ins like "Description".
        query = '[:find ?ident ?title :where [?id :db/ident ?ident] [?id :block/title ?title]]'
        result = self.datascript_query(query)
        for ident, title in result:
            if (
                isinstance(ident, str)
                and isinstance(title, str)
                and ident.startswith(property_ident_prefixes)
                and title.lower() == property_name.lower()
            ):
                return ident
        return None

