"""Runtime capability discovery for the connected Logseq DB instance."""

from dataclasses import asdict, dataclass
from typing import Any

from .client import LogseqDBClient, VERIFIED_WRITE_METHODS, WRITE_METHODS


@dataclass(frozen=True)
class DBCapabilities:
    db_version: str | None
    supported_entity_types: tuple[str, ...]
    supported_write_operations: tuple[str, ...]
    supported_removal_operations: tuple[str, ...]
    supported_query_features: tuple[str, ...]
    supported_read_operations: tuple[str, ...]
    candidate_write_operations: tuple[str, ...]
    unavailable_over_http: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CapabilityDiscovery:
    def __init__(self, client: LogseqDBClient) -> None:
        self._client = client

    async def discover(self) -> DBCapabilities:
        supported_reads: list[str] = []
        entity_types: list[str] = []
        for entity_type, method in (
            ("property", "logseq.DB.getAllProperties"),
            ("tag", "logseq.DB.getAllTags"),
        ):
            if await self._probe(method, []) is not None:
                supported_reads.append(method)
                entity_types.append(entity_type)

        query_features: list[str] = []
        query = "[:find ?entity :where [?entity :block/uuid]]"
        for feature, method in (
            ("datascript", "logseq.DB.datascriptQuery"),
            ("datalog", "logseq.DB.q"),
            ("custom-query", "logseq.DB.customQuery"),
        ):
            if await self._probe(method, [query]) is not None:
                supported_reads.append(method)
                query_features.append(feature)

        removals = tuple(
            sorted(method for method in VERIFIED_WRITE_METHODS if ".remove" in method)
        )

        return DBCapabilities(
            db_version=None,
            supported_entity_types=tuple(entity_types),
            supported_write_operations=tuple(sorted(VERIFIED_WRITE_METHODS)),
            supported_removal_operations=removals,
            supported_query_features=tuple(query_features),
            supported_read_operations=tuple(supported_reads),
            candidate_write_operations=tuple(
                sorted(WRITE_METHODS - VERIFIED_WRITE_METHODS)
            ),
            unavailable_over_http=(
                "logseq.DB.onChanged",
                "logseq.DB.onBlockChanged",
                "logseq.DB.getFavorites",
                "logseq.DB.setPropertyNodeTags",
            ),
        )

    async def _probe(self, method: str, args: list[Any]) -> Any | None:
        try:
            return await self._client.call(method, args)
        except Exception:
            return None

