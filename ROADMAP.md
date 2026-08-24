# Logseq MCP Roadmap

This roadmap describes the current DB-aware derivative of the original
`mcp-logseq` project. Completed items reflect the implementation in `main`.

## Completed

### Architecture and MCP

- ✅ Upgraded to the MCP Python SDK 2.x dependency range.
- ✅ Split the original monolithic API client into focused `logseq/` mixins.
- ✅ Split the original tool module into grouped `tools/` handlers.
- ✅ Added stdio and authenticated HTTP transports.
- ✅ Added read-only server mode and explicit File/DB tool profiles.
- ✅ Added portable local-checkout and GitHub installation documentation.
- ✅ Added ChatGPT remote MCP deployment guidance.

### Logseq DB Graphs

- ✅ Added explicit DB mode with `LOGSEQ_DB_MODE=true`.
- ✅ Added DB page, block, property, tag, search, and batch tools.
- ✅ Added UUID and numeric `db/id` handling.
- ✅ Added typed properties, tag inheritance, journals, tasks, templates,
  flashcards, embeds, assets, queries, views, and Library guidance.
- ✅ Added verified DB route selection with no silent File/DB fallback.
- ✅ Added Datascript-backed block reads and recursive in-memory block trees.
- ✅ Added safe nested expansion for `get_block`, `get_page_data`, and
  `get_page_content` without calling the hanging native `getBlock` routes.
- ✅ Added validated `upsert_nodes` batches for pages, flat blocks, tags, and
  properties.
- ✅ Added dry-run validation, UUID checks, access checks, and read-back rules.

### Safety and Operations

- ✅ Added namespace allowlists and denylists.
- ✅ Added excluded-tag filtering and fail-closed access checks.
- ✅ Added outbound Logseq method and request-shape validation.
- ✅ Added bounded read deadlines and maximum response sizes.
- ✅ Added timeout, restart, and ambiguous-write recovery guidance.
- ✅ Added optional vector search, pluggable embedding providers, and external
  vector synchronization.
- ✅ Added unit, integration, and Windows live-test harness coverage.

### Documentation

- ✅ Updated README, development, testing, API architecture, and installation
  documentation.
- ✅ Added separate DB and file-graph skills.
- ✅ Added project derivation history and original repository references.
- ✅ Added destructive-operation warnings and portable deployment examples.

## Current Limitations

- ⚠️ DB `upsert_nodes` is flat-only on the tested Logseq 2.0.1 API. Logseq
  rejects `parent` and `parent-id` data keys.
- ⚠️ DB `insert_nested_block` is disabled because the native `cli.insertBlock`
  route can time out. Use `upsert_nodes` for supported flat block creation.
- ⚠️ DB namespace page tools return a clean HTTP 500 on the tested Logseq
  2.0.1 build.
- ⚠️ Raw Datascript is an internal implementation detail and is not exposed as
  an MCP tool.
- ⚠️ A timed-out write may have committed. Large changes require chunking,
  dry-run validation, incremental commits, and read-back verification.

## Next Work

### High Priority

- Add a resumable batch-rewrite workflow with operation manifests,
  checkpoints, and duplicate prevention.
- Build a host-side live route regression suite for the supported DB methods.
- Re-test supported write routes across clean Logseq restarts and versions.

### Medium Priority

- Investigate a supported DB hierarchy-writing API when Logseq exposes one.
- Improve bulk Datascript reads with page-scoped queries for very large graphs.
- Add clearer capability metadata for tools unavailable in forced DB mode.

### Low Priority

- Choose and execute a compatibility-aware package and repository rename.
- Maintain version-visible deployment diagnostics for stale client installs.
- Track Logseq DB API changes and update the route manifest as new versions
  become available.

## Notes

- The original project remains at https://github.com/ergut/mcp-logseq.
- This repository is a substantially expanded derivative at
  https://github.com/LoveSkylark/mcp-logseq.
- Logseq API behavior is version-sensitive. Live verification against the
  target Logseq release takes precedence over assumptions from older versions.
