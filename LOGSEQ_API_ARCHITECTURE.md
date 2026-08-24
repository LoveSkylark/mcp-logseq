# LogSeq HTTP API Architecture

This document describes the LogSeq HTTP API architecture based on source code analysis and practical testing.

## Overview

The LogSeq HTTP API runs on `localhost:12315` (default) and acts as a proxy to LogSeq's internal plugin API methods. It bridges external applications to LogSeq's core functionality through JSON-RPC calls.

## Logseq 2.x DB Graph API

Logseq 2.0.1 introduces DB graphs and a native Streamable HTTP MCP server at
`/mcp`. Its MCP implementation delegates to DB-aware API methods exposed
through the same authenticated `/api` endpoint:

- `logseq.cli.getPageData(pageNameOrUuid)` returns a page entity and its block tree.
- `logseq.cli.listPages(options)` lists DB pages with UUIDs and optional expanded data.
- `logseq.cli.listTags(options)` lists tags and optional tag metadata.
- `logseq.cli.listProperties(options)` lists property definitions and schemas.
- `logseq.app.search(searchTerm, options)` searches DB node content.
- `logseq.cli.upsertNodes(operations, options)` validates and applies batched page, block, tag, and property operations; `dry-run` performs validation without committing.

`upsertNodes` is the DB graph batch boundary: the client sends an operations
array once, and Logseq's DB/outliner layer resolves the related operations and
applies the resulting graph changes together. A temporary ID can name a new
page or node so later operations in the same array can reference it. This
reduces HTTP round trips and avoids making each dependent change wait for a
separate response. `dry-run` exercises validation without committing.

DB pages and blocks are nodes identified by UUID and/or numeric `db/id` values.
Properties are typed and may be inherited from tags, so DB clients must preserve
namespaced fields such as `block/title`, `block/uuid`, `block/tags`, and
`logseq.property/*` rather than treating properties as Markdown `key:: value`
lines.

This project supports both modes. `LOGSEQ_DB_MODE=auto` is the default and asks
Logseq which graph type is active. Set it to `true` to force the DB API adapter
or `false` to force legacy Markdown/file behavior, where page files and the
Markdown parser remain the source of truth.

### API namespace policy

The adapter keeps the API namespaces separate:

| Graph mode | Read/write surface | Policy |
| --- | --- | --- |
| Legacy file graph | `logseq.Editor.*` | Use the Markdown/file compatibility handlers. |
| Logseq 2.x DB graph | `logseq.DB.*`, `logseq.cli.*`, and `logseq.app.*` | Use DB node UUIDs and the server-selected DB-safe handlers. |

The verified DB endpoints include `getPageData`, `listPages`, `listTags`,
`listProperties`, `upsertNodes`, and the supported `cli.*` operations in the
route manifest. Block-tree reads use the MCP's internal bulk
`logseq.DB.datascriptQuery` reader because both native `getBlock` routes can
hang on Logseq 2.0.1. Raw Datascript is not exposed as an MCP tool.

### Operation Route Map

`LOGSEQ_DB_MODE` selects an explicit operation route map. It does not perform a
blind string replacement from `logseq.Editor.*` to `logseq.cli.*`, because an
alias can accept a request while still requiring different arguments or exposing
unsafe behavior.

Each logical operation records its file method, DB method, DB verification
status, and notes. Verified DB entries are enabled immediately. Rejected or
untested DB entries fail fast in DB mode; there is no cross-namespace fallback
to `Editor.*`. Promote a route only after live testing confirms its method,
payload, response shape, repeated-call behavior, and read-back result.

Export the current map for the Windows DB test lab with:

```bash
python tests/integration/export-db-route-manifest.py
```

Promote a candidate only after the DB harness records a successful scenario.
This keeps file behavior stable while allowing the DB adapter to migrate one
operation at a time.

### Historical native-route findings

The following findings explain why the current adapter avoids some endpoints.
They are not instructions to call raw routes directly.

- `logseq.cli.getBlock` and `logseq.Editor.getBlock` can hang indefinitely for
  both child options while other API calls remain responsive. The MCP's
  `get_block` operation therefore uses its internal Datascript reader instead.
- Native `getBlockProperties` routes can hang. The MCP keeps the verified route
  map explicit and does not silently substitute an unrelated namespace.
- `logseq.cli.getBlockProperty` hung in an earlier test session. The current
  route map records its status and the handler applies the safe DB path.
- `logseq.cli.addTagExtends`, `removeTagExtends`, `updateBlock`, and
  `createPage` also hung in earlier sessions, but later fresh-restart tests
  verified the current DB mappings. The route manifest is the source of truth.
- `logseq.cli.getPagesFromNamespace`/`logseq.cli.getPagesTreeFromNamespace` are
  not hangs but crash with a clean HTTP 500
  (`Cannot read properties of undefined (reading 'apply')`) - not viable
  either way.

Each hang above was independently confirmed responsive-server-otherwise:
another `cli.*` call made immediately before and after each timeout returned
normally in milliseconds, ruling out a global wedge masking a per-method issue.

### Verified DB methods promoted from live testing (2026-08-23)

`get_property`, `get_tag`, `get_tags_by_name`, `get_tag_objects`, `create_tag`,
`add_tag_property`, and `remove_tag_property` were each live-tested directly
(real non-null responses, verified committed effects for the mutating ones)
and promoted to `logseq.cli.*` in `GRAPH_OPERATION_ROUTES`.

`logseq.cli.upsertProperty` may create plugin-namespaced properties when given
bare names. Resolve existing properties to full idents and prefer
`upsert_nodes` for new properties. The current route map is the source of truth
for whether a DB operation is enabled.

### Known DB property/tag pitfalls (live-tested)

- `resolve_property_ident` (used by `get_property`, `get_block_property`,
  `upsert_block_property`, `set_block_properties`) resolves a display name to
  its full ident with a single joined datascript query
  (`[:find ?ident ?title :where [?id :db/ident ?ident] [?id :block/title ?title]]`).
  An earlier N+1 version (one query per candidate entity) was slow enough on a
  real graph to fail to resolve built-ins such as "Description".
- A bare property/tag name passed to `logseq.Editor.upsertProperty`,
  `logseq.Editor.upsertBlockProperty`, or `logseq.Editor.createTag` that does
  not resolve to an existing ident mints a junk entity under a hardcoded
  `:plugin.property._test_plugin/*` / `:plugin.class._test_plugin/*` identity
  instead of erroring (confirmed live). Always pass a full ident (e.g.
  `:logseq.property/status`) to update an existing property/node; use
  `upsert_nodes` to create a new property/tag cleanly.

The Python MCP process reuses one `requests.Session` for all calls made through
the same configured Logseq endpoint, token, timeout, and graph mode. This is a
process-local connection pool; separate MCP processes or different endpoint
configurations use separate sessions.

## API Endpoint

- **Base URL**: `http://localhost:12315`
- **API Endpoint**: `POST /api`
- **Authentication**: Bearer token required in Authorization header
- **Content-Type**: `application/json`

## Request Format

```json
{
  "method": "logseq.Namespace.methodName",
  "args": [arg1, arg2, ...]
}
```

## Response Format

Standard JSON-RPC response with result or error.

## Internal Architecture

### Request Flow
1. HTTP request hits `/api` endpoint (`server.cljs:142`)
2. Authentication validated via Bearer token (`server.cljs:74-81`)
3. Method name resolved and mapped (`server.cljs:62-72`)
4. Call forwarded to renderer process via IPC (`server.cljs:97-104`)
5. Plugin API method executed in LogSeq context
6. Result returned through the chain

### Method Name Resolution
- API methods follow pattern: `logseq.Namespace.methodName`
- Converted to snake_case internally (e.g., `createPage`  `create_page`)
- Special namespaces: `ui`, `git`, `assets` get `_` suffix

## Verified API Methods

### Editor Namespace (`logseq.Editor.*`)

####  Implemented & Tested
- **`createPage(pageName, properties, options)`**
  - Creates new page with optional properties
  - Options: `{createFirstBlock: true}` creates initial empty block
  - Example: `["My Page", {}, {"createFirstBlock": true}]`

- **`appendBlockInPage(pageName, content)`**
  - Adds content block to existing page
  - Example: `["My Page", "This is content"]`

- **`insertBlock(targetBlockUUID, content, options)`**
  - Inserts a new block relative to an existing block
  - Options: `{sibling: false, properties: {...}}`
  - `sibling: false` inserts as child (default)
  - `sibling: true` inserts as sibling after target
  - Example: `["parent-block-uuid-123", "Child content", {"sibling": false, "properties": {}}]`

- **`getAllPages()`**
  - Returns array of all page objects with metadata
  - Each page includes: name, properties, journal status, etc.

- **`getPage(pageName)`**
  - Returns page object with basic metadata
  - Does not include block content

- **`getPageBlocksTree(pageName)`**
  - Returns hierarchical block structure for page
  - Each block includes: content, properties, children, etc.

#### Legacy file-graph operations

These operations remain supported by the compatibility adapter for file graphs.
They are not the preferred bulk-operation path for DB graphs.

- **`deletePage(pageName)`** - Delete page entirely
- **`updatePage(pageName, properties)`** - Update page properties
- **`updateBlock(blockUUID, content)`** - Update specific block content
- **`removeBlock(blockUUID)`** - Delete specific block

### Graph Namespace (`logseq.App.*`)
- **`getCurrentGraph()`** - Get current graph info
- **`getGraphs()`** - List available graphs (potentially)

### Properties Namespace
- File graphs use first-block property operations for compatibility.
- DB graphs use typed properties through `logseq.cli.upsertNodes` and expose
  property definitions through `logseq.cli.listProperties`.

## Authentication

### Token Management
- Tokens stored in LogSeq config: `:server/tokens`
- Can be array of token objects: `[{:value "token123", ...}, ...]`
- Or simple strings: `["token123", "token456"]`
- Bearer token stripped of "Bearer " prefix before validation

### Token Generation
Generated in LogSeq Settings  Features  HTTP APIs server

## Error Handling

### Common Error Codes
- **401 Unauthorized**: Invalid or missing Bearer token
- **400 Bad Request**: Missing or invalid method name
- **404 Method Not Found**: API method doesn't exist (`MethodNotExist`)
- **500 Internal Error**: LogSeq internal errors

### Error Response Format
```json
{
  "error": {
    "message": "Error description",
    "code": "ERROR_CODE"
  }
}
```

## Limitations

### Search Functionality
- Legacy file graphs use `logseq.App.search`.
- DB graphs use `logseq.app.search`, the lowercase API used by Logseq's native MCP server.
- Search results may contain DB node fields and UUIDs rather than file/page-only records.

### Plugin API Boundary
- HTTP API limited to methods exposed to plugin system
- Not all internal LogSeq functions available
- Some advanced operations may require direct database access

## Configuration

### Environment Variables
- `LOGSEQ_API_TOKEN`: Bearer token for authentication
- `LOGSEQ_API_URL`: API base URL (default: `http://localhost:12315`)

### LogSeq Prerequisites
1. LogSeq application running
2. "Enable HTTP APIs server" checked in Settings  Features
3. Valid API token generated

## Implementation Notes

### Content Retrieval Strategy
- Legacy file graphs combine `getPage(pageName)` and `getPageBlocksTree(pageName)`.
- DB graphs should use `logseq.cli.getPageData(pageNameOrUuid)`, which returns the
  page entity and its block tree in one DB-aware response.

### Block Structure
Blocks returned by `getPageBlocksTree()` can be:
- Dictionary objects: `{"content": "text", "children": [...], ...}`
- Simple strings: `"plain text content"`
- Empty/null values for placeholder blocks

### Page Creation Pattern
To create page with content:
1. `createPage(pageName, {}, {"createFirstBlock": true})`
2. `appendBlockInPage(pageName, content)` (if content needed)

### Nested Block Creation Pattern
To create hierarchical block structures:
1. Create parent block: `appendBlockInPage(pageName, "Parent content")`
2. Get parent block UUID from the returned block data
3. Insert child: `insertBlock(parentBlockUUID, "Child content", {"sibling": false})`
4. Insert another child: `insertBlock(parentBlockUUID, "Second child", {"sibling": false})`
5. Insert sibling: `insertBlock(parentBlockUUID, "Sibling content", {"sibling": true})`

Block hierarchy example:
```
- Parent block
  - Child block 1
  - Child block 2
- Sibling block
```

## Current Status (as of v1.4.0)

15 tools implemented. Block CRUD is complete:

| Operation | Tool | Status |
| --------- | ---- | ------ |
| Read | `get_page_content` | ✅ |
| Create | `insert_nested_block` | ✅ |
| Delete | `delete_block` | ✅ |
| Update | `update_block` | ✅ |

## Future Research Areas
- **Graph context** (`logseq.App.getCurrentGraph`) - Expose which graph is active. Low effort, useful for multi-graph setups.
- **Advanced property management** - Set block-level properties directly (`logseq.Editor.setBlockProperties`). Currently only page properties are writable.
- ~~Asset/file operations via `logseq.Assets.*`~~ - Not useful for AI assistant context.
- ~~UI interaction via `logseq.UI.*`~~ - UI automation from AI is fragile; not worth pursuing.
- ~~Git operations via `logseq.Git.*`~~ - Too niche (requires Logseq's built-in git sync).

---

*Last Updated: 2026-02-24*
*Based on LogSeq source analysis and MCP server implementation*