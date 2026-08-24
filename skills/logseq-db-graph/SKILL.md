---
name: logseq-db-graph
description: Detailed rules for safely reading, planning, and writing a Logseq 2.0.x DB graph through mcp-logseq. Use UUIDs, typed properties, DB-native page data, and validated upsert batches. Never use Markdown file-graph workflows.
---

# Logseq DB Graphs over MCP

This skill applies only to a Logseq 2.0.x DB graph. The MCP server must run
with `LOGSEQ_DB_MODE=true`. Do not use this skill with a Markdown/file graph.

This server communicates with a DB graph through DB-safe routes. The internal
database query implementation is not an MCP tool and must never be called by
Claude Desktop. Call only the MCP tool names listed in this skill; the server
selects the safe route. DB mode never uses `logseq.Editor.*`. Confirm
`LOGSEQ_DB_MODE=true` before continuing if file-graph behavior appears.

> **Warning:** This MCP can create, edit, move, and delete Logseq pages,
> blocks, tags, properties, and other graph data. Use backups, review planned
> changes, and grant destructive permission deliberately. The AI client may ask
> for confirmation, but this MCP cannot guarantee that a prompt will appear.

**Hard rule for Claude Desktop:** In DB mode, `query` is not available and
`datascriptQuery` is not available. Do not search for either tool, propose
either tool, or call either tool. Use `search_blocks` for text discovery,
`get_page_data` for page structure, and `get_block` for one known block.

**Tool boundary:** The names in this skill are MCP tool names, not raw Logseq
API method names. Never send `logseq.*` method names, invent a tool, or bypass
the MCP tool list. `logseq.DB.datascriptQuery` is an internal implementation
detail used by the server and is never callable from Claude Desktop.

## Scope and configuration

This skill is deliberately DB-only. Use a dedicated MCP server with:

```json
{
  "LOGSEQ_DB_MODE": "true",
  "LOGSEQ_API_CONNECT_TIMEOUT": "10",
  "LOGSEQ_API_READ_TIMEOUT": "60",
  "PYTHONIOENCODING": "utf-8"
}
```

Do not use `LOGSEQ_DB_MODE=auto` with this skill. Do not load the file-graph
skill in the same Claude conversation.

## DB data model

- Pages, blocks, tags, and properties are DB nodes identified by UUIDs or DB IDs.
- Properties are typed; do not write Markdown `key:: value` lines.
- Tags are first-class class/tag nodes.
- Use UUID references, not page-name links, when creating DB node relationships.
- DB endpoints may return namespaced fields (`block/title`, `block/uuid`) or
  bare fields (`title`, `uuid`). Treat both as valid representations.

Never use these file-graph conventions in a DB graph:

- Markdown `key:: value` property lines.
- YAML frontmatter as a property mechanism.
- Slash-separated page names as namespace hierarchy.
- File-page replacement or Markdown parsing to reorganize a DB page.

## Operational stance

Preserve existing material. A factual correction is a targeted block edit, not
a page rewrite. A change that affects a page's organization, multiple sections,
or an unclear source of truth requires a user decision before mutation.

Treat every mutation as potentially committed even if the request times out.
Read back before retrying, and never queue a blind duplicate write.

## Build the change plan in memory first

Do all discovery and reasoning before the first mutation. Hold a structured
change plan in the conversation, not as speculative partial edits in Logseq.

For every proposed change, record:

```text
target page: page title and UUID
target block: block UUID, current text, and parent/page UUID
intent: create | edit | remove | attach property | attach tag
replacement: exact final text or typed value
evidence: source fact or user instruction
dependencies: required page, block, property, or tag UUIDs
verification: exact search or page-data check after commit
```

Before deployment, check the plan for:

1. Duplicate target blocks or contradictory replacements.
2. A change that answers an "open question" but leaves the stale question in
  place.
3. A heading, summary, or cross-reference made inaccurate by the edit.
4. Name-based links or property values that should instead reference known UUIDs.
5. Missing required typed property schemas or tag/class nodes.

Draft the final text for all changed blocks before invoking a write tool. Keep
voice, formatting, and the page's existing structure unless the user requested
reorganization.

## Read workflow

1. Use `search_blocks` to find distinctive content and collect page/block UUIDs.
  Read `content` rather than highlighted search titles.
2. Use `get_page_data` to obtain the page entity and its blocks, nested
  children included by default (`expand_children` defaults to `true`). Child
  trees use the safe Datascript-backed block reader and do not call
  `cli.getBlock` or `Editor.getBlock`. Pass `expand_children=false` only when
  you specifically want the faster flat top-level-only list.
3. Normalize relevant nodes in memory: retain each block's UUID, title/content,
  parent, children, tags, and typed properties. Do not infer a relationship
  from display text when a UUID is available.
4. When inspecting one known block, use `get_block(block_uuid,
  include_children=true)`. In DB mode this uses Datascript to build the block
  tree and does not need the owning page.
5. Use `list_pages`, `list_tags`, and `list_properties` to discover existing
  entities before creating any of them.

Do not use `get_page_content` as the primary DB page reader. In DB mode,
`include_children=false` returns child UUID references without recursively
expanding each child.

## Prepare typed data

DB properties and tags are not text decoration.

1. Use `list_properties(expand=true)` before creating or assigning a typed
  property. Confirm its type, cardinality, and any class restrictions.
2. Use `list_tags(expand=true)` before attaching a tag/class or defining a
  class relationship.
3. Resolve existing pages, tags, properties, and target blocks to UUIDs.
4. Put only exact UUIDs or verified temporary IDs in the mutation plan.
5. For built-in Logseq concepts, prefer the supported DB API/schema. Do not
  claim that inserting text such as `alias::` or `tags::` changed a DB property.

Use full property idents when writing typed properties, for example
`:logseq.property/status`. Display names can be resolved, but full idents avoid
plugin-namespaced duplicates and are the canonical DB representation.

## Deploy mutations

Use `upsert_nodes` for related changes. It is the DB-native batch boundary and
avoids repeated individual single-node writes.

1. Convert the completed in-memory plan into `operations`.
2. Use `add` or `edit` with `entityType` of `page`, `block`, `tag`, or
  `property`.
3. Give a new entity a unique temporary ID when a later operation in the same
  batch depends on it.
4. `upsert_nodes` commits run a `dry_run=true` preflight by default. Repair
   every reported validation problem in the plan; do not commit a modified
   subset blindly.
5. Submit the validated operations with `dry_run=false` once. Disable the
   preflight only with an explicit `validate_before_commit=false` decision.
6. Verify the exact expected state with `get_page_data` and `search_blocks`.

For an individual typed property/tag operation that cannot be represented by a
batch, use the matching DB property/tag handler only after reading the current
entity and schema. `update_block`, `upsert_block_property`,
`remove_block_property`, `add_block_tag`, `remove_block_tag`, `add_tag_extends`,
`remove_tag_extends`, `upsert_property`, `remove_property`, and `create_page`
work on DB graphs for exactly this case -- each is a single `cli.*` write.
`insert_nested_block` is unavailable in DB mode because `cli.insertBlock` can
time out; use `upsert_nodes` for supported flat block creation. Prefer
`upsert_nodes` for anything batchable, especially a new page plus its
blocks/tags/properties in one call.

### Verified batch semantics

- `dry_run=true` builds the complete DB import data and returns the change
  summary without committing.
- A non-dry `upsert_nodes` request applies the complete import through one
  Logseq `batch-import-edn!` transaction. Logseq reports a transaction error
  instead of a successful partial summary.
- One batch can add or edit `block`, `page`, `tag`, and `property` nodes. Use
  temporary IDs to connect dependent additions inside the same batch.
- This is the preferred path for bulk imports and related edits. It avoids the
  repeated single-write pattern that can wedge Logseq.
- `upsert_nodes` is flat-only in Logseq 2.0.1. Do not send `parent-id`,
  `parent`, `block/parent`, `properties`, `order`, or other undocumented keys.
  Strict validation rejects these by default; `LOGSEQ_UPSERT_STRICT=false` is a
  temporary compatibility escape hatch for a future Logseq release.

Do not generalize this reliability claim to every `logseq.cli.*` alias. Prefer
the native DB methods this service verifies and exposes, then verify every
committed batch by reading the graph.

## Queries and DB schema

The `query` MCP tool is file-graph-only and is not available in DB mode.
Existing DB query blocks may contain Logseq DSL text, but that text is stored
content for interpretation, not an MCP command to execute. Do not search for
or call a `query` tool in DB mode. There is also no `datascriptQuery` MCP tool,
and Claude Desktop must not call raw Logseq API methods. The server uses its
internal database reader behind `get_block` and nested `get_page_data` reads,
where it can apply access controls. For DB discovery, use `search_blocks`,
`get_page_data`, `list_pages`, `list_tags`, and `list_properties`.

When using DB queries or interpreting DB page data, use DB schema names:

| File-graph concept | DB graph equivalent |
| --- | --- |
| `:block/content` | `:block/title` |
| `:block/original-name` | `:block/title` |
| `:block/marker` | `:logseq.property/status` |
| `:block/left` | `:block/order` |

Similarly, use DB DSL forms such as `(property key)` and `(tags tag)` rather
than file-graph forms such as `(page-property key)` and `(page-tags tag)`.

`get_page_data` includes each top-level block's full nested children by
default (`expand_children` defaults to `true`). The server internally uses one
bulk Datascript snapshot and assembles the tree in memory, so it does not call
the hanging `cli.getBlock` or `Editor.getBlock` routes. Claude Desktop should
call `get_page_data` or `get_block`, never `datascriptQuery` directly.
`get_page_content` inherits the same behavior. For a single known block,
`get_block` uses the same Datascript-backed reader.

## DB feature playbook

Logseq DB graphs model most features as tagged nodes, typed properties, and
relationships. Use the MCP tools to read and write the graph data; do not ask
for an unexposed raw Datascript tool or imitate UI-only commands with Markdown
syntax.

### Nodes, pages, and journals

- A node is either a page or block. Both can be referenced with `[[]]`, tagged,
  favorited, collapsed, embedded, and given properties.
- Blocks are created inside pages. Blocks do not have unique display names, so
  identify them by UUID.
- Pages are unique by title and tag. Do not assume a title alone identifies one
  page when tags distinguish pages.
- Journals are pages tagged `#Journal`, created for dates in the Journals view.
  A date property value links to the corresponding journal page. Journal
  behavior is date-driven, not a Markdown filename convention.
- To customize every journal, configure properties on the `#Journal` tag. Use
  `get_page_data` for a journal page and `upsert_nodes` for supported content
  changes.
- Ordinary page deletion is recycled for up to 30 days. Deleting a tag,
  property, or today's journal is permanent. Verify the target type before
  deleting.

### Tags and tag inheritance

- A tag is a first-class node. Use `list_tags(expand=true)` before selecting or
  creating one, and use `add_block_tag` or `upsert_nodes` to apply it.
- Tag properties are inherited by every node carrying that tag. Use tags as
  reusable schemas or types, not merely as text labels.
- Tags can extend multiple parent tags. Child tags inherit their parents'
  properties. Use `add_tag_extends` and `remove_tag_extends` for one-off
  relationship changes, and verify the resulting tag afterward.
- A tag can be converted to a page and a page can be converted to a tag in the
  Logseq UI. Do not simulate conversion by renaming or duplicating nodes.
- A tag on a node is normally displayed beside the node. Inline tag text and
  semantic tag assignment are different behaviors; preserve the node's tag
  data rather than inserting `#tag` into content as a substitute.
- A Node-type property may restrict values to a tag and its descendant tags.
  Resolve those tag UUIDs before writing values.

### Properties

- Properties can be attached to pages, blocks, tags, and property nodes. In DB
  graphs they are typed entities, not `key:: value` lines.
- Use `list_properties(expand=true)` to inspect type, choices, defaults,
  cardinality, UI position, and restrictions before writing.
- The main types are Text, Number, Date, DateTime, Checkbox, Url, and Node.
  Number values are numeric; Date and DateTime values are temporal; Checkbox
  values are boolean; Node values reference nodes.
- Text is the flexible default. Url values are constrained URLs. Node values
  may be restricted to a tag and its descendants.
- Multiple values are supported for most types, but not Checkbox or DateTime.
  Respect the existing schema instead of replacing a value with an array by
  assumption.
- Property choices constrain Text, Url, and Number values. Checkbox mappings
  can map choices to checked/unchecked display states.
- Built-in properties such as `Status`, `Priority`, `Deadline`, and
  `Scheduled` power task behavior. Preserve their canonical idents and schema.
- Page properties live on the page title node, not on the first child block.
- Resolve display names to full idents before mutation. A bare name can create
  a plugin-namespaced duplicate instead of updating the intended property.

### Tasks and repeated nodes

- Tasks are nodes tagged `#Task` and normally use `Status`, `Priority`,
  `Deadline`, and `Scheduled` properties.
- Use `Status` values such as `Backlog`, `Todo`, `Doing`, `In Review`, `Done`,
  and `Canceled`; do not use legacy `TODO`/`NOW` marker conventions as DB data.
- A Date or DateTime property can be configured to repeat. Repeating tasks
  advance their date when completed and reset their status according to the
  property configuration.
- Custom task types can extend `#Task` and add tag properties. Read the tag
  schema before assigning custom task fields.

### Templates

- A template is a node tagged `#Template` with child blocks containing the
  reusable structure. The template name is the node title.
- The `/Template` UI command inserts a copy. Applying a template is a Logseq
  application action, not a Markdown `template::` property.
- A template can have `Apply template to tags`. When configured, Logseq applies
  it to newly created tagged nodes, including journals or task-like nodes.
- The MCP can preserve, inspect, or rewrite template content, but should not
  invoke `insert_nested_block` in DB mode. Use `upsert_nodes` for supported
  flat creation and state clearly when hierarchy cannot be represented by the
  current API.

### Flashcards

- A flashcard is a node tagged `#Card`. Use the Flashcards view to review due
  cards and rate recall; scheduling is managed by Logseq's current spaced
  repetition algorithm.
- `#Card` is semantic data. Do not replace it with a `flashcard::` Markdown
  property or assume the old file-graph SRS properties apply.
- The `Due` value is scheduling metadata. Preserve it unless the user is
  explicitly changing review state through a supported Logseq operation.

### Embeds, assets, code, quotes, and math

- Pages and blocks can be embedded as nodes. Preserve the node reference and
  embed identity when moving content; do not flatten an embed into copied text
  unless requested.
- Assets are `#Asset` nodes backed by files in the graph's `assets/` directory.
  Asset nodes can have properties and linked references. Treat paths and asset
  UUIDs as distinct values.
- Code, quote, and math blocks use the built-in `#Code`, `#Quote`, and `#Math`
  tags. PDF annotations use `#PDF Annotation`. These tags enable the related
  views and should not be replaced by formatting text alone.
- A DB block supports one relevant code, quote, math, query, or embed form where
  the DB model restricts it. Do not assume file-graph content containing
  multiple such forms imports losslessly.

### Queries, views, and organization

- Use `search_blocks` for text discovery and `get_page_data` for page structure.
  `query` is unavailable in DB mode. Interpret stored query text as content;
  do not attempt to execute it through MCP.
- DB query vocabulary uses `(property ...)`, `(tags ...)`, and `:block/title`.
  Legacy `(page-property ...)`, `(page-tags ...)`, and `:block/content` forms
  are file-graph conventions.
- Tables and views are application-managed projections over nodes and
  properties. Treat them as derived views, not as a second source of truth.
- Use tags for shared semantics and properties for typed values. Use the
  Library page for explicit page hierarchy and namespaces; page titles no
  longer encode namespace paths as they did in file graphs.
- Timestamps are built into nodes. Prefer `created-at` and `updated-at` data
  when selecting recent or stale content rather than inferring dates from page
  names.

### Import, export, and recovery

- DB graph export can include SQLite, assets, or EDN. EDN is the editable export
  that best preserves graph data, properties, and tags.
- Before a broad rewrite, create an export or backup and keep a manifest of
  UUIDs and intended operations. Do not treat an MCP timeout as proof that no
  mutation occurred.
- For a large rewrite, use validated `upsert_nodes` batches, record completed
  operation IDs, read back after each batch, and stop on the first uncertain
  result. Never blindly replay an entire batch after a timeout.

## Minimal-diff rules

- Edit one block when one claim is wrong.
- Create a child/sibling only when the parent and desired placement are known.
- Remove a block only when its subtree is intentionally obsolete. Deletion
  cascades to the entire subtree with no `recursive` flag or child count in
  the response, so inspect it with `get_block` (`include_children=true`) before
  deleting it.
- `delete_page` soft-deletes (recycles) an ordinary page; it is safe to use
  directly. Tags, properties, and today's journal delete permanently instead
  -- that is Logseq's own recycle-bin behavior.
- Do not rewrite a whole page to correct a sentence.
- If a correction resolves an obsolete question or placeholder, remove or
  replace the obsolete material in the same planned change.

Avoid repeated individual single-node writes: Logseq 2.0.1 can wedge its write
path after a small run of them, and a wedged write can make an otherwise-
working route (e.g. `delete_block`) look permanently broken when it is really
just stuck until a Logseq restart. A timed-out write may have committed, so
read back before retrying.

## Text formatting rules

- Use ASCII punctuation in generated Logseq content.
- Do not use em dashes. Use a period, comma, colon, parentheses, or a new
  sentence instead.
- Preserve the page's existing heading, list, indentation, and emphasis style.
- Keep blocks concise and give each block one clear idea.
- Use Markdown links and emphasis only when they match the surrounding page.
- Do not insert Markdown property syntax such as `key:: value` into DB content.

## DB-safe tool choices

| Need | Use |
|---|---|
| Find content | `search_blocks` |
| Read a page/tree | `get_page_data` |
| Read a known block | `get_block` |
| Discover pages | `list_pages` |
| Discover classes/tags | `list_tags` |
| Discover typed schemas | `list_properties` |
| Batch mutation | `upsert_nodes` |
| Typed property/tag operation | DB property/tag handlers |

### Tool selection rules

- Use `search_blocks` for DB text discovery. The general `search` tool is
  available in mixed or auto deployments, but `search_blocks` is the explicit
  DB workflow and returns block UUIDs and page identifiers.
- Use `get_page_data` for DB page reads. `get_page_content` is available for
  compatibility, but it is not the primary DB reader.
- Use `get_block` for a known DB block. It uses the server's internal bulk
  Datascript reader and does not call either native `getBlock` endpoint.
- Use `upsert_nodes` for DB batch creation and edits. Use one dry-run, then one
  commit, and verify the resulting state before continuing.
- Do not use `insert_nested_block` in DB mode. It is unavailable because the
  underlying single-node insert route can time out. `upsert_nodes` cannot set
  hierarchy on Logseq 2.0.1 either; do not send `parent` or `parent-id`.
- Do not use `query` in DB mode. Stored query text can be read and explained,
  but it cannot be executed through the DB skill.
- Do not call `logseq.DB.datascriptQuery`, `logseq.cli.*`, `logseq.app.*`, or
  `logseq.Editor.*` directly. Those are server-side routes, not MCP tools.

## Full tool inventory (DB mode)

Every MCP tool name registered when `LOGSEQ_DB_MODE=true`, grouped by area.
There is no other Logseq access available -- do not invent a tool name or
call a raw Logseq API method directly.

- **Pages**: `create_page`, `list_pages`, `get_page_data`, `get_page_content`,
  `delete_page`, `rename_page`.
- **Blocks**: `get_block`, `update_block`, `delete_block`.
- **Properties**: `get_property`, `upsert_property`, `remove_property`,
  `list_properties`, `get_block_properties`, `get_block_property`,
  `upsert_block_property`, `remove_block_property`, `set_block_properties`.
- **Tags**: `get_tag`, `get_tag_objects`, `get_tags_by_name`, `create_tag`,
  `list_tags`, `add_block_tag`, `remove_block_tag`, `add_tag_property`,
  `remove_tag_property`, `add_tag_extends`, `remove_tag_extends`.
- **Search and batch**: `search`, `search_blocks`, `upsert_nodes`.
- **Vector (optional, only if configured)**: `vector_search`, `sync_vector_db`,
  `vector_db_status`.

Not available in DB mode (file-graph-only; do not attempt): `update_page`,
`query`, `find_pages_by_property`, `get_pages_from_namespace`,
`get_pages_tree_from_namespace`, `get_page_backlinks`, `insert_nested_block`.
Use `upsert_nodes` or
`get_page_data` plus in-memory filtering for the equivalent DB-mode need.

## Failure handling

- A first-time timeout usually indicates an unsafe argument shape. Stop and
  compare arguments to the verified workflow before retrying, and consider
  whether prior failed writes in the same session have wedged the write path
  (a Logseq restart clears it) rather than assuming the route is broken.
- DB `get_block` uses the MCP's Datascript-backed reader for both values of
  `include_children`; `false` returns child UUID references without expanding
  descendant objects. It does not call Logseq's hanging native `getBlock` API.
- `get_page_data` is the DB-native page reader; prefer it directly over
  `get_page_content` for clarity, even though `get_page_content` also works
  in DB mode now (it delegates to `get_page_data` internally).
- If a previously successful write call begins timing out while search still
  works, Logseq is wedged. Stop issuing write calls, verify state with
  search, then restart Logseq, restart its HTTP API server, and start a new
  Claude conversation.
- A timed-out write may have committed. Search or read page data before any
  retry, then update the in-memory plan to match the observed state.

## Response discipline

Before a destructive, broad, or ambiguous change, present the plan to the user:

- the pages/blocks affected;
- the exact intended replacements;
- the properties/tags to be changed;
- any source conflicts or uncertain interpretation; and
- the verification step after deployment.

Do not claim success solely because a mutation request returned. Claim success
only after the planned verification finds the intended DB state.