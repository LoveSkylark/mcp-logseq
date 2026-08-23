"""DB tag LogSeq client methods."""
import logging
from typing import Any

logger = logging.getLogger("mcp-logseq")

class TagMixin:
    def get_tag(self, tag_name_or_ident: str) -> Any:
        return self._call_api(self._method_for("get_tag"), [tag_name_or_ident])

    def get_tags_by_name(self, tag_name: str) -> Any:
        return self._call_api(self._method_for("get_tags_by_name"), [tag_name])

    def get_tag_objects(self, tag_name_or_ident: str) -> Any:
        return self._call_api(self._method_for("get_tag_objects"), [tag_name_or_ident])

    def create_tag(self, tag_name: str, options: dict | None = None) -> Any:
        return self._call_api(self._method_for("create_tag"), [tag_name, options or {}])

    def add_tag_property(self, tag_id: str, property_id_or_name: str) -> Any:
        return self._call_api(
            self._method_for("add_tag_property"), [tag_id, property_id_or_name]
        )

    def remove_tag_property(self, tag_id: str, property_id_or_name: str) -> Any:
        return self._call_api(
            self._method_for("remove_tag_property"), [tag_id, property_id_or_name]
        )

    def add_tag_extends(self, tag_id: str, parent_tag_id_or_name: str) -> Any:
        return self._call_api(
            self._method_for("add_tag_extends"), [tag_id, parent_tag_id_or_name]
        )

    def remove_tag_extends(self, tag_id: str, parent_tag_id_or_name: str) -> Any:
        return self._call_api(
            self._method_for("remove_tag_extends"), [tag_id, parent_tag_id_or_name]
        )

    def add_block_tag(self, block_uuid: str, tag_id: str) -> Any:
        return self._call_api(self._method_for("add_block_tag"), [block_uuid, tag_id])

    def remove_block_tag(self, block_uuid: str, tag_id: str) -> Any:
        return self._call_api(self._method_for("remove_block_tag"), [block_uuid, tag_id])

