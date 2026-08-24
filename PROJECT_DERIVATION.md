# Project Derivation and Change History

## Relationship to the Original Project

This repository began as a branch of the original `mcp-logseq` project:

- Original repository: https://github.com/ergut/mcp-logseq
- Original design and structure: https://github.com/ergut/mcp-logseq
- Current repository: https://github.com/LoveSkylark/mcp-logseq

The original project remains the reference for the initial file-graph MCP
server, its Markdown-oriented behavior, and its original module layout. This
repository now contains a substantially different implementation focused on
Logseq 2.x DB graphs while retaining compatibility with legacy Markdown/file
graphs.

The Python distribution and console command are still named `mcp-logseq` for
compatibility. A future release should consider a distinct name, such as
`mcp-logseq-db`, `mcp-logseq-next`, or another project-specific name, after a
migration plan is prepared for imports, configuration, and existing users.

## Original Design and Structure

The original project was centered around a single API client and a single tool
module:

```text
src/mcp_logseq/
    __init__.py       CLI entry point
    logseq.py         Logseq HTTP API client
    tools.py          MCP tool handlers
    server.py         MCP server registration and transport
    parser.py         Markdown parsing and formatting
    settings.py       Environment-based API settings
```

Its primary assumptions were:

- Logseq pages and journals are Markdown files.
- Page and block content is represented with file-graph Markdown structures.
- Properties use `key:: value` syntax.
- `logseq.Editor.*` is the main API surface.
- A mostly shared tool catalog serves the file-graph workflow.
- The MCP server is a thin bridge between an AI client and the Logseq HTTP API.

See the original repository for its source history, original README, API
client, parser, and tool-handler design.

## Current Architecture

The implementation now separates responsibilities into packages:

```text
src/mcp_logseq/
    __init__.py
    server.py
    settings.py
    config.py
    access.py
    namespace.py
    parser.py
    logseq/
        __init__.py       Route manifest and composed API client
        pages.py          Page operations
        blocks.py         Block operations and DB tree reads
        properties.py     Property operations and Datascript helpers
        tags.py           Tag operations
        search.py         Search, DSL, and DB batch operations
    tools/
        __init__.py       Shared handlers, validation, access control
        pages.py          Page handlers
        blocks.py         Block handlers
        properties.py     Property handlers
        tags.py           Tag handlers
        search.py         Search and query handlers
        db_native.py      DB-native handlers
    vector/
        ...               Optional semantic search and synchronization
```

The client uses an explicit logical operation route map. File graphs use
`logseq.Editor.*`; DB graphs use verified `logseq.cli.*`, `logseq.app.*`, or
internal `logseq.DB.datascriptQuery` implementations as appropriate. There is
no silent cross-graph fallback.

## Implemented Changes

### Logseq DB graph support

- Added Logseq 2.x DB graph mode through `LOGSEQ_DB_MODE`.
- Added automatic graph-mode detection for non-skill deployments.
- Added DB-native page, tag, property, search, and batch-node operations.
- Added support for DB node UUIDs and numeric `db/id` values.
- Added support for bare and namespaced DB response fields.
- Added DB schema handling for `:block/title`, typed properties, tags, and
  parent/child relationships.
- Added DB-specific page, block, property, tag, and search tools.
- Added DB-only and file-only tool registration profiles.

### Safe DB block reads

- Replaced the hanging native DB `getBlock` path with a Datascript-backed
  implementation.
- Added bulk block attribute retrieval through one internal
  `logseq.DB.datascriptQuery` snapshot.
- Added in-memory recursive construction of block trees.
- Added safe nested-child expansion for `get_block`, `get_page_data`, and
  `get_page_content`.
- Kept raw Datascript inaccessible as an MCP tool so access control remains
  server-side.
- Added cycle protection while constructing block trees.
- Preserved `include_children=false` as a shallow result with child UUID
  references.

### DB batch writes

- Added `upsert_nodes` for validated DB page, block, tag, and property batches.
- Added dry-run validation before commits.
- Added strict operation and entity validation.
- Added UUID validation for edits, tags, and references.
- Added validation for required titles and page IDs.
- Added support for temporary IDs within a batch.
- Documented that Logseq 2.0.1 rejects `parent`, `parent-id`, and other
  undocumented hierarchy keys in `upsertNodes`.
- Disabled DB `insert_nested_block` because the native single-node
  `cli.insertBlock` route can time out.
- Directed DB users to `upsert_nodes` for supported flat block creation.

### API route verification and safety

- Added `GraphOperationRoute` and an explicit DB/file route manifest.
- Verified many `cli.*` routes against Logseq 2.0.1 with read-back checks.
- Rejected known unsafe or broken routes rather than silently falling back to
  a different API namespace.
- Added an outbound API method allowlist.
- Added validation that every outbound request contains only `method` and
  `args`, with `args` as a list.
- Prevented unknown or malformed API requests from reaching Logseq.
- Documented Logseq route-specific lockups and the need to restart after a
  wedged request.
- Added bounded read deadlines and maximum response sizes.
- Added clearer transport failure messages.

### Access control and data protection

- Added namespace allowlists and denylists.
- Added excluded-tag filtering.
- Applied access checks to page, block, tag, search, vector, and write paths.
- Added fail-closed behavior when ownership or access information cannot be
  resolved.
- Added DB-aware entity and property handling for access checks.

### Property and tag improvements

- Added typed DB property reads and writes.
- Added property ident resolution from display names.
- Fixed built-in bare-ident handling.
- Fixed reverse ident resolution for namespaced properties.
- Replaced an N+1 property lookup with a joined Datascript query.
- Added DB property extraction from block attributes.
- Added tag inheritance and tag-extends support.
- Added tag property and block-tag operations.
- Documented plugin-namespaced duplicates caused by bare property/tag names.

### Search and vector capabilities

- Added DB-native `search_blocks` behavior with UUID and page metadata.
- Added DB property enrichment for search results.
- Added optional vector search, indexing, synchronization, and status tools.
- Added pluggable embedding providers, including local and hosted providers.
- Added namespace and tag filtering to vector retrieval and indexing.

### MCP and project structure

- Upgraded the MCP dependency to `mcp>=2,<3`.
- Split the original large `logseq.py` into focused client mixins.
- Split the original large `tools.py` into focused handler modules.
- Added explicit read-only tool registration behavior.
- Added stdio and HTTP transports.
- Added HTTP bearer authentication.
- Added loopback binding defaults and TLS/insecure binding guardrails.
- Added structured logging and local log files.
- Added response bounding for oversized MCP reads.
- Added Windows DB integration harnesses and route-manifest tooling.
- Expanded unit and integration coverage for DB routes, access controls,
  properties, transport, and tool registration.

### Claude Desktop skills and documentation

- Added a dedicated DB graph skill.
- Added a dedicated file graph skill.
- Made the skills mutually exclusive by graph type.
- Added DB guidance for journals, tasks, tags, tag inheritance, typed
  properties, templates, flashcards, embeds, assets, queries, views, Library
  organization, import/export, and recovery.
- Explicitly documented that `query` is unavailable in DB mode.
- Explicitly documented that raw `datascriptQuery` is an internal implementation
  detail, not an MCP tool.
- Documented the distinction between MCP tool names and raw Logseq API method
  names.
- Added guidance for validated, resumable, read-back-verified large rewrites.

## Important Current Limitations

- DB `upsert_nodes` is flat-only on the tested Logseq 2.0.1 API. Hierarchical
  `parent` and `parent-id` keys are rejected by Logseq.
- DB `insert_nested_block` is disabled because `cli.insertBlock` can time out.
- Raw Datascript is not exposed as an MCP tool.
- The DB `query` MCP tool is not available in forced DB mode.
- Namespace page tools are unavailable in DB mode because the tested Logseq
  API returns a clean HTTP 500 for those routes.
- Large rewrites should be chunked, dry-run validated, committed, and read
  back incrementally. A timeout can still mean that a write committed.
- The project name remains `mcp-logseq` until a deliberate compatibility-aware
  rename is made.

## Verification Baseline

The current branch has been tested with the repository's containerized Python
workflow. The latest full test run before this document was created passed all
project tests. Live API verification must still be performed on the user's
Windows host because the Podman container cannot access the host's loopback
Logseq API directly.

## Naming Recommendation

Treat this repository as a distinct DB-capable successor or derivative rather
than a small patch release of the original project. Before renaming:

1. Choose the new distribution and command name.
2. Decide whether to retain a compatibility package or wrapper named
   `mcp-logseq`.
3. Update the GitHub repository, package metadata, README, skills, and Claude
   Desktop examples together.
4. Provide a migration note for existing environment variables and MCP
   configurations.
5. Keep the original repository link in this document as historical context.
