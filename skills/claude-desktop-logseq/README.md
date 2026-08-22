# Installing This Skill in Claude Desktop

This folder contains the `logseq-mcp-writing` skill for Claude Desktop. The skill
teaches Claude how to use the `mcp-logseq` service with both Logseq file graphs
and Logseq 2.x DB graphs, preferring DB-native tools when detection reports a DB graph.

## 1. Configure the MCP service

Add `mcp-logseq` to Claude Desktop's MCP configuration first. The service needs
at least:

```json
{
  "mcpServers": {
    "logseq": {
      "command": "/absolute/path/to/uvx",
      "args": ["--with", "mcp>=2,<3", "mcp-logseq"],
      "env": {
        "LOGSEQ_API_TOKEN": "your-logseq-api-token",
        "LOGSEQ_DB_MODE": "auto",
        "LOGSEQ_API_CONNECT_TIMEOUT": "10",
        "LOGSEQ_API_READ_TIMEOUT": "60"
      }
    }
  }
}
```

Use `LOGSEQ_DB_MODE=true` to force DB mode or `false` to force legacy Markdown
file mode. Restart Claude Desktop after changing its MCP configuration.

## 2. Add the skill

Use Claude Desktop's **Settings > Capabilities > Skills** area, when available,
and import or add this folder:

```text
/absolute/path/to/mcp-logseq/skills/claude-desktop-logseq
```

The imported skill must contain `SKILL.md` at its top level. Keep the folder name
and the `name`/`description` frontmatter in `SKILL.md` unchanged so Claude can
identify the skill.

If your Claude Desktop build does not provide a Skills importer, use the
product's project instructions or custom instructions area and add the contents
of `SKILL.md` there. The MCP server configuration and the skill are separate:
adding the MCP server does not automatically load this skill.

## 3. Reload Claude Desktop

1. Save the skill or import it through the Skills settings.
2. Fully quit Claude Desktop, including its menu-bar or system-tray process.
3. Relaunch Claude Desktop.
4. Start a new conversation so the skill and MCP tool list are loaded together.

## 4. Verify it is active

Ask Claude:

```text
Which Logseq graph mode is active, and which tools should you use for a DB graph?
```

For a DB graph, Claude should prefer `get_page_data`, `search_blocks`, typed
property/tag handlers, and `upsert_nodes`. For a file graph, it should use
`get_page_content`, `search`, `query`, and the regular page/block handlers.

## Notes

- Logseq must be running with its HTTP API server enabled.
- `LOGSEQ_API_TOKEN` is required by the MCP service.
- The default `LOGSEQ_DB_MODE=auto` asks Logseq which graph type is active.
- Timeout values are seconds; use numeric values such as `60`, not an empty string.
- Keep this skill directory readable by the Claude Desktop process.
