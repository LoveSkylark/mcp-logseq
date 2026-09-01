# Repository instructions

The new `mcp-logseq-db/` project uses the MCP Python SDK v2 and is intentionally
limited to verified `logseq.DB.*` API methods. Do not add calls to other Logseq
namespaces or expose a candidate method before live timeout, response-shape,
repeatability, and read-back testing.

MCP SDK references:

- https://py.sdk.modelcontextprotocol.io/get-started/
- https://py.sdk.modelcontextprotocol.io/api/mcp/