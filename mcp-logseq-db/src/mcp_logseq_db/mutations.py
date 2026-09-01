"""DB property mutations with exact resolution and mandatory read-back."""

from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID
import httpx

from .client import LogseqDBClient


@dataclass(frozen=True)
class MutationResult:
    response: Any
    verified_state: Any
    recovered_after_timeout: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VerifiedMutations:
    def __init__(self, client: LogseqDBClient) -> None:
        self._client = client

    async def upsert_property(
        self,
        title: str,
        schema: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> MutationResult:
        if not title.strip():
            raise ValueError("Property title must not be empty")
        response, timed_out = await self._write(
            "logseq.DB.upsertProperty", [title, schema, options or {}]
        )
        if timed_out:
            raise RuntimeError(
                "Property upsert timed out before Logseq returned the generated ident; "
                "the result is ambiguous and must be resolved from getAllProperties"
            )
        if not isinstance(response, dict) or not response.get("ident"):
            raise RuntimeError("Property upsert did not return an exact ident")
        ident = self._validated_ident(str(response["ident"]))
        current = await self._client.call("logseq.DB.getProperty", [ident])
        if not self._has_ident(current, ident):
            raise RuntimeError(f"Write verification failed for property {ident}")
        return MutationResult(response, current, timed_out)

    async def remove_property(self, property_ident: str) -> MutationResult:
        ident = self._validated_ident(property_ident)
        existing = await self._client.call("logseq.DB.getProperty", [ident])
        if not self._has_ident(existing, ident):
            raise LookupError(f"No property exists with exact ident {ident}")

        response, timed_out = await self._write("logseq.DB.removeProperty", [ident])
        current = await self._client.call("logseq.DB.getProperty", [ident])
        if current is not None:
            detail = " after a timeout" if timed_out else ""
            raise RuntimeError(f"Property {ident} is still visible{detail}")
        return MutationResult(response, None, timed_out)

    async def create_tag(
        self, title: str, options: dict[str, Any] | None = None
    ) -> MutationResult:
        if not title.strip():
            raise ValueError("Tag title must not be empty")
        response, timed_out = await self._write(
            "logseq.DB.createTag", [title, options or {}]
        )
        if timed_out:
            raise RuntimeError("Tag creation timed out before returning its identity")
        if not isinstance(response, dict) or not response.get("ident"):
            raise RuntimeError("Tag creation did not return an exact ident")
        current = await self._client.call("logseq.DB.getTag", [response["ident"]])
        if not isinstance(current, dict) or current.get("uuid") != response.get("uuid"):
            raise RuntimeError("Tag creation verification failed")
        return MutationResult(response, current)

    async def add_tag_property(
        self, tag_uuid: str, property_ident: str
    ) -> MutationResult:
        tag_uuid = self._validated_uuid(tag_uuid)
        property_entity = await self._property(property_ident)
        response, timed_out = await self._write(
            "logseq.DB.addTagProperty", [tag_uuid, property_ident]
        )
        current = await self._tag(tag_uuid)
        if property_entity["id"] not in current.get(":logseq.property.class/properties", []):
            raise RuntimeError("Tag property addition verification failed")
        return MutationResult(response, current, timed_out)

    async def remove_tag_property(
        self, tag_uuid: str, property_ident: str
    ) -> MutationResult:
        tag_uuid = self._validated_uuid(tag_uuid)
        property_entity = await self._property(property_ident)
        property_uuid = self._validated_uuid(str(property_entity.get("uuid")))
        response, timed_out = await self._write(
            "logseq.DB.removeTagProperty", [tag_uuid, property_uuid]
        )
        current = await self._tag(tag_uuid)
        if property_entity["id"] in current.get(":logseq.property.class/properties", []):
            raise RuntimeError("Tag property removal verification failed")
        return MutationResult(response, current, timed_out)

    async def add_tag_extends(
        self, tag_uuid: str, parent_tag_uuid: str
    ) -> MutationResult:
        tag_uuid = self._validated_uuid(tag_uuid)
        parent = await self._tag(parent_tag_uuid)
        response, timed_out = await self._write(
            "logseq.DB.addTagExtends", [tag_uuid, self._validated_uuid(parent_tag_uuid)]
        )
        current = await self._tag(tag_uuid)
        if parent["id"] not in current.get(":logseq.property.class/extends", []):
            raise RuntimeError("Tag inheritance addition verification failed")
        return MutationResult(response, current, timed_out)

    async def remove_tag_extends(
        self, tag_uuid: str, parent_tag_uuid: str
    ) -> MutationResult:
        tag_uuid = self._validated_uuid(tag_uuid)
        parent = await self._tag(parent_tag_uuid)
        response, timed_out = await self._write(
            "logseq.DB.removeTagExtends", [tag_uuid, self._validated_uuid(parent_tag_uuid)]
        )
        current = await self._tag(tag_uuid)
        if parent["id"] in current.get(":logseq.property.class/extends", []):
            raise RuntimeError("Tag inheritance removal verification failed")
        return MutationResult(response, current, timed_out)

    async def upsert_block_property(
        self,
        block_uuid: str,
        property_ident: str,
        value: Any,
        options: dict[str, Any] | None = None,
    ) -> MutationResult:
        block_uuid = self._validated_uuid(block_uuid)
        await self._property(property_ident)
        response, timed_out = await self._write(
            "logseq.DB.upsertBlockProperty",
            [block_uuid, property_ident, value, options or {}],
        )
        current = await self._entity(block_uuid)
        if property_ident not in current:
            raise RuntimeError("Block property upsert verification failed")
        return MutationResult(response, current, timed_out)

    async def remove_block_property(
        self, block_uuid: str, property_ident: str
    ) -> MutationResult:
        block_uuid = self._validated_uuid(block_uuid)
        await self._property(property_ident)
        response, timed_out = await self._write(
            "logseq.DB.removeBlockProperty", [block_uuid, property_ident]
        )
        current = await self._entity(block_uuid)
        if property_ident in current:
            raise RuntimeError("Block property removal verification failed")
        return MutationResult(response, current, timed_out)

    async def add_block_tag(self, block_uuid: str, tag_uuid: str) -> MutationResult:
        block_uuid = self._validated_uuid(block_uuid)
        tag = await self._tag(tag_uuid)
        response, timed_out = await self._write(
            "logseq.DB.addBlockTag", [block_uuid, self._validated_uuid(tag_uuid)]
        )
        current = await self._entity(block_uuid)
        if tag["id"] not in self._reference_ids(current.get("tags", [])):
            raise RuntimeError("Block tag addition verification failed")
        return MutationResult(response, current, timed_out)

    async def remove_block_tag(self, block_uuid: str, tag_uuid: str) -> MutationResult:
        block_uuid = self._validated_uuid(block_uuid)
        tag = await self._tag(tag_uuid)
        response, timed_out = await self._write(
            "logseq.DB.removeBlockTag", [block_uuid, self._validated_uuid(tag_uuid)]
        )
        current = await self._entity(block_uuid)
        if tag["id"] in self._reference_ids(current.get("tags", [])):
            raise RuntimeError("Block tag removal verification failed")
        return MutationResult(response, current, timed_out)

    async def set_block_icon(
        self, block_uuid: str, icon_type: str, icon_name: str
    ) -> MutationResult:
        block_uuid = self._validated_uuid(block_uuid)
        if icon_type not in {"tabler-icon", "emoji"}:
            raise ValueError("icon_type must be 'tabler-icon' or 'emoji'")
        response, timed_out = await self._write(
            "logseq.DB.setBlockIcon", [block_uuid, icon_type, icon_name]
        )
        current = await self._entity(block_uuid)
        if current.get(":logseq.property/icon") != {"type": icon_type, "id": icon_name}:
            raise RuntimeError("Block icon verification failed")
        return MutationResult(response, current, timed_out)

    async def remove_block_icon(self, block_uuid: str) -> MutationResult:
        block_uuid = self._validated_uuid(block_uuid)
        response, timed_out = await self._write(
            "logseq.DB.removeBlockIcon", [block_uuid]
        )
        current = await self._entity(block_uuid)
        if ":logseq.property/icon" in current:
            raise RuntimeError("Block icon removal verification failed")
        return MutationResult(response, current, timed_out)

    async def _write(self, method: str, args: list[Any]) -> tuple[Any, bool]:
        try:
            return await self._client.call(method, args), False
        except httpx.TimeoutException:
            return None, True

    async def _property(self, ident: str) -> dict[str, Any]:
        ident = self._validated_ident(ident)
        entity = await self._client.call("logseq.DB.getProperty", [ident])
        if not self._has_ident(entity, ident):
            raise LookupError(f"No property exists with exact ident {ident}")
        return entity

    async def _tag(self, tag_uuid: str) -> dict[str, Any]:
        tag_uuid = self._validated_uuid(tag_uuid)
        entity = await self._client.call("logseq.DB.getTag", [tag_uuid])
        if not isinstance(entity, dict) or entity.get("uuid") != tag_uuid:
            raise LookupError(f"No tag exists with exact UUID {tag_uuid}")
        return entity

    async def _entity(self, entity_uuid: str) -> dict[str, Any]:
        query = (
            "[:find (pull ?entity [*]) . :where "
            f"[?entity :block/uuid #uuid \"{entity_uuid}\"]]"
        )
        entity = await self._client.call("logseq.DB.datascriptQuery", [query])
        if not isinstance(entity, dict) or entity.get("uuid") != entity_uuid:
            raise LookupError(f"No entity exists with exact UUID {entity_uuid}")
        return entity

    @staticmethod
    def _validated_ident(value: str) -> str:
        if not isinstance(value, str) or not value.startswith(":") or "/" not in value:
            raise ValueError(
                "Expected an exact namespaced property ident such as :user.property/status"
            )
        return value

    @staticmethod
    def _validated_uuid(value: str) -> str:
        try:
            return str(UUID(value))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError(f"Expected an exact UUID, got {value!r}") from error

    @staticmethod
    def _has_ident(entity: Any, expected_ident: str) -> bool:
        if not isinstance(entity, dict):
            return False
        return str(entity.get("db/ident", entity.get("ident"))) == expected_ident

    @staticmethod
    def _reference_ids(references: Any) -> set[int]:
        if not isinstance(references, list):
            return set()
        return {
            reference["id"]
            for reference in references
            if isinstance(reference, dict) and isinstance(reference.get("id"), int)
        }