---
name: claude-desktop-logseq-db
description: Detailed rules for safely reading, planning, and writing a Logseq 2.0.x DB graph through mcp-logseq. Use UUIDs, typed properties, DB-native page data, and validated upsert batches. Never use Markdown file-graph workflows.
---

# Logseq DB Graphs over MCP

This skill applies only to a Logseq 2.0.x DB graph. The MCP server must run
with `LOGSEQ_DB_MODE=true`. Do not use this skill with a Markdown/file graph.

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
2. Use `get_page_data` to obtain the page entity and its full block tree.
3. Normalize relevant nodes in memory: retain each block's UUID, title/content,
  parent, children, tags, and typed properties. Do not infer a relationship
  from display text when a UUID is available.
4. When inspecting one block and its owner page is known, use
  `get_block(block_uuid, page_name, include_children=true)`. This reads stable
  page data and extracts the matching block without the fragile direct API.
5. Use `list_pages`, `list_tags`, and `list_properties` to discover existing
  entities before creating any of them.

Do not use `get_page_content` as the primary DB page reader. Do not pass
`include_children=false` to `get_block`.

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

## Deploy mutations

Use `upsert_nodes` for related changes. It is the DB-native batch boundary and
avoids repeated individual `Editor.*` writes.

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
entity and schema.

### Verified batch semantics

- `dry_run=true` builds the complete DB import data and returns the change
  summary without committing.
- A non-dry `upsert_nodes` request applies the complete import through one
  Logseq `batch-import-edn!` transaction. Logseq reports a transaction error
  instead of a successful partial summary.
- One batch can add or edit `block`, `page`, `tag`, and `property` nodes. Use
  temporary IDs to connect dependent additions inside the same batch.
- This is the preferred path for bulk imports and related edits. It avoids the
  repeated `Editor.*` write pattern that can wedge Logseq.

Do not generalize this reliability claim to every `logseq.cli.*` alias. Prefer
the native DB methods this service verifies and exposes, then verify every
committed batch by reading the graph.

## Queries and DB schema

`query` is this MCP server's Logseq DSL query tool. Use it for supported DSL
filters and discovery, but do not assume it exposes unrestricted Datascript.
Raw `logseq.DB.datascriptQuery` is available through Logseq's HTTP API for
advanced structural investigation, but is not a general MCP tool because raw
queries cannot be safely filtered by this server's access policy.

When using DB queries or interpreting DB page data, use DB schema names:

| File-graph concept | DB graph equivalent |
| --- | --- |
| `:block/content` | `:block/title` |
| `:block/original-name` | `:block/title` |
| `:block/marker` | `:logseq.property/status` |
| `:block/left` | `:block/order` |

Similarly, use DB DSL forms such as `(property key)` and `(tags tag)` rather
than file-graph forms such as `(page-property key)` and `(page-tags tag)`.

## Minimal-diff rules

- Edit one block when one claim is wrong.
- Create a child/sibling only when the parent and desired placement are known.
- Remove a block only when its subtree is intentionally obsolete.
- Do not delete pages through MCP. DB page deletion can flatten inbound links;
  ask the user to delete through the Logseq UI.
- Do not rewrite a whole page to correct a sentence.
- If a correction resolves an obsolete question or placeholder, remove or
  replace the obsolete material in the same planned change.

Avoid repeated individual `Editor.*` writes: Logseq 2.0.1 can wedge after a
small run of them. A timed-out write may have committed, so read back before
retrying. Do not use `delete_page`; delete DB pages in the Logseq UI.

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
| Read a known block | `get_block` with `page_name` |
| Discover pages | `list_pages` |
| Discover classes/tags | `list_tags` |
| Discover typed schemas | `list_properties` |
| Batch mutation | `upsert_nodes` |
| Typed property/tag operation | DB property/tag handlers |

## Failure handling

- A first-time timeout usually indicates an unsafe argument shape. Stop and
  compare arguments to the verified workflow before retrying.
- `get_block(include_children=false)` is a known Logseq 2.0.1 hang. Always use
  `true`; prefer providing `page_name` when it is available.
- `Editor.getPageBlocksTree` is a known DB-mode hang. Use `get_page_data`.
- If a previously successful `Editor.*` call begins timing out while search
  still works, Logseq is wedged. Stop issuing Editor calls, verify state with
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