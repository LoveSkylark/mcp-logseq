# Install the DB Graph Skill

Import this folder into Claude Desktop Skills:

```text
/absolute/path/to/mcp-logseq/skills/claude-desktop-logseq-db
```

Configure a dedicated DB-graph MCP server. Do not set `LOGSEQ_DB_MODE=auto` for
this skill.

```json
{
  "mcpServers": {
    "logseq-db": {
      "command": "/absolute/path/to/uvx",
      "args": ["--with", "mcp>=2,<3", "mcp-logseq"],
      "env": {
        "LOGSEQ_API_TOKEN": "your-logseq-api-token",
        "LOGSEQ_DB_MODE": "true",
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

Fully quit Claude Desktop before changing its configuration, then relaunch it
and begin a new conversation.
