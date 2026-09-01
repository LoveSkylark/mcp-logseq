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

Read the fields precisely:

- `supported_read_operations` and `supported_query_features` were probed
  against the connected process during this call.
- `supported_write_operations` and `supported_removal_operations` are the
  server's dated, promoted write manifest. They are not destructive startup
  probes. A listed method may still fail if the connected Logseq build differs.
- `candidate_write_operations` are allowed internally for further controlled
  testing but are not MCP capabilities. Do not call or advertise them.
- `unavailable_over_http` methods are rejected for this server/build and must
  not be retried.

The Logseq API is version-sensitive. The tool list and current capability
result take precedence over examples or remembered behavior.

## Node model

Read this before reasoning about graph structure. Pages, blocks, tags, and
properties share Logseq's entity store and commonly expose `:block/uuid` and
`:block/title`. Their attributes and tags determine their role; pages normally
carry `:block/name`.

- `:block/parent` references the immediate page or block ancestor.
- `:block/page` is the denormalized owning page and is independent of the
  immediate parent for nested blocks.
- `:block/order` is a fractional-index string used to order siblings.

This MCP has no page/block content or hierarchy mutation tool, but the model
still matters when reading query results. A nested node whose `:block/page`
points to a non-page is malformed even if Logseq renders it under its parent.
When investigating structure, verify parent and owning page independently.

Use this bounded diagnostic when malformed ownership is suspected:

```clojure
[:find (pull ?entity [:db/id :block/title
                      {:block/page [:db/id :block/title]}])
 :where
 [?entity :block/page ?page]
 [(missing? $ ?page :block/name)]]
```

## DB identity rules

Logseq DB entities can expose bare fields such as `id`, `ident`, `uuid`, and
`title`.

- Properties: read and remove by exact namespaced ident, for example
  `:logseq.property/status` or `:plugin.property._test_plugin/MyProperty`.
- Tags: `db_get_tag` accepts exact ident, UUID, or resolvable title.
  `db_get_tags_by_name` follows Logseq's normalized internal-name lookup and a
  display title may not resolve for every plugin-created tag. Prefer
  `db_get_all_tags`, then retain the returned ident and UUID. All tag mutations
  use exact tag UUIDs.
- The MCP accepts a property ident for both tag-property tools. For removal,
  the server resolves that ident to the property UUID required by Logseq.
- A bare property display name is rejected by this MCP before HTTP when an
  exact ident is required. Continue to pass full idents.
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
- On the tested build, adding an extension replaced the existing Root parent
  rather than appending another parent. Read the child's
  `:logseq.property.class/extends` before and after the write, preserve the
  prior parent, and explain the replacement risk to the user.
- Removing that extension restored Root in the verified test. Read back rather
  than assuming restoration on another build.

### Tagging a block

- `db_add_block_tag(block_uuid, tag_uuid)` adds a semantic DB tag.
- `db_remove_block_tag(block_uuid, tag_uuid)` removes it.
- Do not insert `#tag` text as a substitute for changing `:block/tags`.

## Block icons

- `db_set_block_icon` accepts `icon_type` of `tabler-icon` or `emoji`.
- For `tabler-icon`, pass the Tabler ID such as `flask`.
- For `emoji`, pass the case-sensitive emoji-mart display name, such as
  `Test Tube` or `Books`. Do not pass a literal glyph (`🧪`), shortcode,
  lowercase ID (`test_tube`), or plural ID (`books`). Logseq resolves the
  display name and stores its normalized ID.
- `db_remove_block_icon` removes the icon from an exact block UUID.
- The server reads back `:logseq.property/icon` after both operations.

## Verification and timeout handling

Every exposed write returns an envelope containing `response`,
`verified_state`, and `recovered_after_timeout`. A successful HTTP status alone
is not considered success.

- `response` is often `null` for a successful Logseq mutation. Treat it as the
  raw API result, not verification evidence.
- `verified_state` is the server's post-write read-back. Claim success only
  when it contains the expected attribute or relationship.
- For `db_remove_property`, both `response` and `verified_state` are `null`
  after verified absence. For relationship/icon removals, `verified_state`
  normally contains the surviving entity without the removed value.
- `recovered_after_timeout=true` means the original response was ambiguous but
  read-back established the resulting state. Mention that recovery explicitly.
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
  exposed and it remains a candidate.
- `onChanged` and `onBlockChanged`: callback APIs cannot cross the ordinary
  request/response HTTP boundary.
- File reads/writes: `setFileContent` is a candidate, not a supported tool. No
  real DB file target has passed write/read-back/cleanup verification.
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

### Capability claims

- A tool description describes one endpoint, not the complete DB schema.
- Do not infer a graph-wide limitation from one tool refusal. Distinguish
  unavailable MCP functionality from an impossible DB state.
- Conversely, do not claim capability because the UI renders a result. Verify
  the underlying attributes through an exact read.
- Label findings with the MCP server and Logseq build that produced them. Do
  not transfer behavior from the legacy `mcp-logseq` server to this one.
- Communicate the boundary early: this server supports queries and metadata
  writes, but not page/block content or hierarchy writes.