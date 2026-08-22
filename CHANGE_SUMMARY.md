# Deployment Update

## Added Functionality

- Consolidated MCP tool handlers into `src/mcp_logseq/tools.py`.
- Added page and block operations, namespace and tag access control, page-property handling, and bulk node upserts.
- Added reusable HTTP connections for LogSeq API calls.
- MCP tool calls reuse one persistent LogSeq API session per process and configuration, reducing connection churn during multi-step operations.
- Added configurable API connect/read timeouts and HTTPS certificate verification.
- Added database mode support for LogSeq installations that expose database-specific data.
- Added LogSeq 2.x DB graph reads, native search, UUID-based page data, and DB-backed vector indexing while retaining the legacy Markdown graph path.
- Added native DB tag and property discovery tools.
- Added typed DB property access, tag/class relationship operations, and DB node/task/asset listings.
- Added read-only server mode, which hides content-changing tools while keeping read and search tools available.
- Added asynchronous thread offloading so synchronous API calls do not block the MCP event loop.
- Kept vector search, vector status, and external vector-sync tools available when vector support is configured.

## Deployment Notes

- Set `LOGSEQ_API_TOKEN` before starting the server.
- Optional settings include `LOGSEQ_API_URL`, `LOGSEQ_API_CONNECT_TIMEOUT`, `LOGSEQ_API_READ_TIMEOUT`, `LOGSEQ_VERIFY_SSL`, and `LOGSEQ_DB_MODE` (`auto` by default, `true`, or `false`).
- Use read-only mode for deployments where the assistant must not modify LogSeq content.
- Configure `LOGSEQ_CONFIG_FILE` with `vector.enabled=true` to expose vector tools.

## Validation

- Python syntax compilation passed for the changed modules.
- All server-registered tool handlers are present.
- Runtime tests were not run because dependencies such as `requests` and `pytest` are not installed in the current environment.
