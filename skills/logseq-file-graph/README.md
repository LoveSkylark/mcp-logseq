# Install the File Graph Skill

Import this folder into Claude Desktop Skills:

```text
E:\git\mcp-logseq\skills\logseq-file-graph
```

Configure a dedicated legacy Markdown/file-graph MCP server. Do not set
`LOGSEQ_DB_MODE=auto` for this skill.

```json
{
  "mcpServers": {
    "logseq-file": {
      "command": "C:\\Users\\YOUR_USER\\.local\\bin\\uv.exe",
      "args": ["run", "--project", "E:\\git\\mcp-logseq", "mcp-logseq"],
      "env": {
        "LOGSEQ_API_TOKEN": "your-logseq-api-token",
        "LOGSEQ_API_URL": "http://127.0.0.1:12315",
        "LOGSEQ_DB_MODE": "false",
        "LOGSEQ_API_CONNECT_TIMEOUT": "10",
        "LOGSEQ_API_READ_TIMEOUT": "60",
        "MCP_READ_TOOL_TIMEOUT": "90",
        "MCP_MAX_RESPONSE_CHARS": "30000",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

The file-graph skill uses Markdown pages, `key:: value` properties, page names,
and `logseq.Editor.*`-backed operations. Do not load it together with the DB
skill in the same Claude conversation.

Fully quit Claude Desktop before changing its configuration, then relaunch it
and begin a new conversation.
