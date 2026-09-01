---
name: logseq-db-native
description: "Use when reading or modifying a Logseq 2.x DB graph through the mcp-logseq-db server. Covers DB queries, exact property and tag identities, verified metadata writes, destructive-operation safeguards, and timeout recovery. Never use file-graph or non-DB Logseq tools."
---

# Logseq DB-Native MCP

**Verified provenance:** Logseq 2.0.1 DB graph, `mcp-logseq-db` 0.1.0,
live-tested 2026-09-01. Revalidate version-sensitive claims after changing
either Logseq or the MCP server.

Use this skill only with the `mcp-logseq-db` server and a Logseq 2.x DB graph.
This server is intentionally narrow. It exposes verified `db_*` MCP tools
backed exclusively by the `logseq.DB.*` API namespace.

Do not load the legacy `logseq-db-graph` or `logseq-file-graph` skill in the
same conversation.

## Hard boundaries

- Before doing any graph work, inspect the available connector and tools. The
  connector must be `mcp-logseq-db` and must expose the `db_*` inventory below.
  If the connector is named `logseq`, or tools such as `upsert_nodes`,
  `create_page`, `search_blocks`, or `get_page_data` appear, the legacy server
  is active. Stop and ask the user to restart Claude Desktop with the correct
  configuration. Do not adapt this skill to the legacy tool catalog.
- Call only the MCP tool names listed in this skill. Never call or emit a raw
  `logseq.*` API method.
- Never invent a page, block, search, batch, file, monitoring, or deletion
  tool that is not in the current MCP tool list.
- Do not use Markdown `key:: value`, YAML frontmatter, file paths, or page-file
  replacement as substitutes for DB properties.
- The server cannot create, rename, update, or remove page/block content.
- The server cannot remove tags. `db_create_tag` is therefore not reversible
  through this MCP.
- File operations and callback subscriptions are unavailable.

## Start every workflow with capabilities

Call `db_capabilities` once near the start of a conversation. Treat its
reported read methods as probes of the connected Logseq process. Supported
write methods come from the server's dated live-verification manifest; they
are not re-probed on startup because doing so would mutate the graph. Candidate
methods have not passed complete read-back testing and must not be called.

The Logseq API is version-sensitive. The tool list and current capability
result take precedence over examples or remembered behavior.

## DB identity rules

Logseq DB entities can expose bare fields such as `id`, `ident`, `uuid`, and
`title`.

- Properties: read and remove by exact namespaced ident, for example
  `:logseq.property/status` or `:plugin.property._test_plugin/MyProperty`.
- Tags: reads may use exact ident, UUID, or exact title. All tag mutations use
  exact tag UUIDs.
- Blocks/nodes: all metadata mutations use exact block UUIDs.
- Never select a destructive target from a fuzzy search result alone.
- Resolve the entity, show its exact identity, and validate its current state
  before removal.

`db_upsert_property` accepts a display title. Logseq may generate a
plugin-namespaced ident. Always retain the exact ident returned in
`verified_state`; use that ident for later reads and removal.

## Read workflow

1. Call `db_capabilities`.
2. Use the narrowest structured reader available:
   - `db_get_all_properties` to discover property definitions.
   - `db_get_property` for one exact property ident.
   - `db_get_all_tags` to discover tags/classes.
   - `db_get_tag` for one exact tag identity.
   - `db_get_tags_by_name` for an exact title lookup.
   - `db_get_tag_objects` for nodes associated with a known tag.
3. Use `db_q`, `db_custom_query`, or `db_datascript_query` only when the
   structured readers cannot answer the question.
4. Preserve `id`, `ident`, and `uuid` in the working plan. Do not reduce an
   entity to display text.

### Query discipline

- Queries are read-only discovery tools. Do not attempt transaction forms.
- Prefer bounded queries that return only fields needed for the task.
- Use DB attributes such as `:block/title`, `:block/uuid`, and `:block/tags`.
- Validate query results before using any returned UUID in a write.
- Avoid dumping the entire graph when a property, tag, UUID, or title filter
  can narrow the result.

Example exact-UUID Datascript lookup:

```clojure
[:find (pull ?entity [*]) .
 :where
 [?entity :block/uuid #uuid "BLOCK_UUID"]]
```

## Plan before writing

For each mutation, establish this plan in the conversation:

```text
target: exact title plus UUID or property ident
current state: relevant properties, tags, inheritance, or icon
operation: exact db_* MCP tool
requested state: exact typed value or relationship
reversibility: removal tool or explicit lack of one
verification: field and identity expected after the write
```

Ask for confirmation before:

- `db_remove_property`;
- creating a tag, because the MCP cannot remove it;
- removing a property/tag relationship that may affect inherited schemas; or
- changing metadata on multiple nodes.

## Property workflow

### Create or update a property

1. Call `db_get_all_properties` and check for an existing exact title/ident.
2. Choose a valid schema type: `date`, `number`, `checkbox`, `default`,
   `string`, `node`, `url`, `datetime`, `json`, or `asset`.
3. Call `db_upsert_property(title, schema, options)` once.
4. Retain the generated ident from `verified_state`.
5. Do not retry blindly if the tool reports an ambiguous timeout.

### Remove a property

1. Call `db_get_property` with the exact namespaced ident.
2. Confirm the returned ident exactly matches the requested target.
3. Explain that property removal is destructive.
4. Call `db_remove_property` only after confirmation.
5. The server verifies that `db_get_property` returns no entity afterward.

### Block properties

- Use `db_upsert_block_property` with an exact block UUID and property ident.
- Use `db_remove_block_property` with the same exact identities.
- Inspect the property schema before assigning a value.
- The server verifies attribute presence or absence through DB read-back.

## Tag workflow

### Discover and create

- Use `db_get_all_tags`, `db_get_tag`, or `db_get_tags_by_name` before creating
  a tag.
- Call `db_create_tag` only when no existing exact tag is suitable.
- State before creation that this MCP has no tag-removal operation.
- Retain the returned tag UUID and ident.

### Tag properties and inheritance

- `db_add_tag_property(tag_uuid, property_ident)` adds a property to a tag.
- `db_remove_tag_property(tag_uuid, property_ident)` removes it. The server
  resolves the property ident to the UUID form required by Logseq.
- `db_add_tag_extends(tag_uuid, parent_tag_uuid)` adds inheritance.
- `db_remove_tag_extends(tag_uuid, parent_tag_uuid)` removes inheritance.
- Read the child tag before and after changing its schema or parentage.

### Tagging a block

- `db_add_block_tag(block_uuid, tag_uuid)` adds a semantic DB tag.
- `db_remove_block_tag(block_uuid, tag_uuid)` removes it.
- Do not insert `#tag` text as a substitute for changing `:block/tags`.

## Block icons

- `db_set_block_icon` accepts `icon_type` of `tabler-icon` or `emoji` and the
  corresponding icon name/value.
- `db_remove_block_icon` removes the icon from an exact block UUID.
- The server reads back `:logseq.property/icon` after both operations.

## Verification and timeout handling

Every exposed write performs server-side read-back. A successful HTTP status
alone is not considered success.

- Claim success only when the MCP result contains the expected
  `verified_state`.
- A timed-out write may have committed. Never immediately repeat it.
- Read the exact target with a fresh tool call and reconcile observed state.
- If creation timed out before Logseq returned a generated ident, stop and
  inspect the property/tag listings for a uniquely matching title.
- One failed, malformed, cancelled, or timed-out request must not prevent a
  later normal request. Report repeated failures rather than issuing a loop.

## Known unavailable or rejected behavior

- `getFavorites`: rejected after HTTP 500 on the tested Logseq 2.0.1 build.
- `setPropertyNodeTags`: rejected after a live timeout.
- Property value choices: transport returned success, but the requested effect
  was not observable through the available property reader, so no MCP tool is
  exposed.
- `onChanged` and `onBlockChanged`: callback APIs cannot cross the ordinary
  request/response HTTP boundary.
- File reads/writes: no real DB file target has passed verification.
- Page/block content creation, editing, movement, and deletion: no approved
  `logseq.DB.*` methods are available in this server.

## Tool inventory

Reads and capabilities:

- `db_capabilities`
- `db_q`
- `db_custom_query`
- `db_datascript_query`
- `db_get_all_properties`
- `db_get_property`
- `db_get_all_tags`
- `db_get_tag`
- `db_get_tags_by_name`
- `db_get_tag_objects`

Verified writes:

- `db_upsert_property`
- `db_remove_property`
- `db_create_tag`
- `db_add_tag_property`
- `db_remove_tag_property`
- `db_add_tag_extends`
- `db_remove_tag_extends`
- `db_upsert_block_property`
- `db_remove_block_property`
- `db_add_block_tag`
- `db_remove_block_tag`
- `db_set_block_icon`
- `db_remove_block_icon`

## Response discipline

Before writing, state the exact entities and intended changes. After writing,
summarize the verified result, any generated ident, and any remaining
irreversible fixture or uncertainty. Never claim that unsupported page/block
content work was completed through metadata-only tools.