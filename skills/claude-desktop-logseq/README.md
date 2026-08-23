# Logseq Claude Desktop Skills

The mixed-mode skill has been replaced to prevent file-graph and DB-graph
instructions from being loaded together.

Choose exactly one skill and use the matching forced MCP configuration:

| Graph type | Skill folder | Required setting |
| --- | --- | --- |
| Logseq 2.x DB graph | `claude-desktop-logseq-db` | `LOGSEQ_DB_MODE=true` |
| Legacy Markdown/file graph | `claude-desktop-logseq-file` | `LOGSEQ_DB_MODE=false` |

Do not import this folder: it no longer contains a `SKILL.md`. See the README
in the chosen skill folder for its Claude Desktop configuration and import path.
