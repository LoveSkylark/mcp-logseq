# mcp-logseq-db

A narrow MCP server built specifically around the Logseq 2.x
`logseq.DB.*` HTTP API. It does not call `logseq.cli.*`, `logseq.App.*`,
`logseq.app.*`, or `logseq.Editor.*`.

## Current tools

- `db_capabilities`
- `db_q`
- `db_custom_query`
- `db_datascript_query`
- `db_get_all_properties`
- `db_get_property`
- `db_get_all_tags`
- `db_get_tag`
- `db_get_tags_by_name`
- `db_get_tag_objects`
- `db_upsert_property`
- `db_remove_property`
- `db_create_tag`
- `db_add_tag_property`
- `db_remove_tag_property`
- `db_add_tag_extends`
- `db_remove_tag_extends`
- `db_upsert_block_property`
- `db_remove_block_property`
- `db_add_block_tag`
- `db_remove_block_tag`
- `db_set_block_icon`
- `db_remove_block_icon`

Every HTTP call uses a new client and sends `Connection: close`. Connect and
read timeouts are configured independently. Property writes are read back after
the mutation; removals require an exact namespaced ident and verify absence.

## Setup

```powershell
cd mcp-logseq-db
python -m pip install -e ".[dev]"
$env:LOGSEQ_API_TOKEN = "your-token"
python -m mcp_logseq_db.server
```

Environment variables:

| Variable | Default |
| --- | --- |
| `LOGSEQ_API_TOKEN` | Required |
| `LOGSEQ_API_URL` | `http://127.0.0.1:12315` |
| `LOGSEQ_API_CONNECT_TIMEOUT` | `3` seconds |
| `LOGSEQ_API_READ_TIMEOUT` | `15` seconds |
| `LOGSEQ_VERIFY_SSL` | `true` |

The workspace `.vscode/mcp.json` prompts for the token and starts the same
stdio server without storing the token.

## Claude Desktop skill

Import `dist/logseq-db-native.zip` through Claude Desktop Skills. The editable
skill source is in `skills/logseq-db-native/`. Use this skill only with the
`mcp-logseq-db` connector; do not enable the legacy DB/file graph skills in the
same conversation.

## Live verification baseline

Tested against the local Logseq 2.0.1 DB graph on 2026-09-01:

| Method | Result |
| --- | --- |
| `logseq.DB.getAllProperties` | HTTP 200; bare-field property array |
| `logseq.DB.getProperty` | HTTP 200; exact property ident required |
| `logseq.DB.getAllTags` | HTTP 200; bare-field tag array |
| `logseq.DB.getTag` | HTTP 200 for ident, UUID, and exact title |
| `logseq.DB.getTagsByName` | HTTP 200; exact title returns an array |
| `logseq.DB.getTagObjects` | HTTP 200; no positive instances in test graph |
| `logseq.DB.q` | HTTP 200 |
| `logseq.DB.customQuery` | HTTP 200 |
| `logseq.DB.datascriptQuery` | HTTP 200 |
| `logseq.DB.upsertProperty` | HTTP 200; `(title, schema, options)` |
| `logseq.DB.removeProperty` | HTTP 200; exact ident; absence verified |
| `logseq.DB.createTag` | HTTP 200; `(title, options)`; exact identity verified |
| `logseq.DB.addTagProperty` | HTTP 200; tag UUID and property ident; verified |
| `logseq.DB.removeTagProperty` | HTTP 200; tag UUID and property UUID; verified |
| `logseq.DB.addTagExtends` | HTTP 200; child and parent tag UUIDs; verified |
| `logseq.DB.removeTagExtends` | HTTP 200; child and parent tag UUIDs; verified |
| `logseq.DB.upsertBlockProperty` | HTTP 200; block UUID and property ident; verified |
| `logseq.DB.removeBlockProperty` | HTTP 200; block UUID and property ident; verified |
| `logseq.DB.addBlockTag` | HTTP 200; block and tag UUIDs; verified |
| `logseq.DB.removeBlockTag` | HTTP 200; block and tag UUIDs; verified |
| `logseq.DB.setBlockIcon` | HTTP 200; Tabler ID and case-sensitive emoji-mart display name verified |
| `logseq.DB.removeBlockIcon` | HTTP 200; absence verified |
| `logseq.DB.addPropertyValueChoices` | HTTP 200; effect not observable; not exposed |
| `logseq.DB.getFileContent` | HTTP 200/null for missing path; not exposed |
| `logseq.DB.getFavorites` | HTTP 500; blocked |
| `logseq.DB.setPropertyNodeTags` | Timed out; blocked |

The timed-out `setPropertyNodeTags` request was followed by successful normal
requests and exact cleanup without restarting Logseq or the test process.

All promoted writes also passed through MCP in one reversible end-to-end run.
Emoji names `Test Tube` and `Books` were verified; Logseq stores their normalized
IDs `test_tube` and `books`. The F4A2 malformed child/grandchild and tag were
removed. Its ten pages are recycled, so their blocks remain queryable, and the
user property `MCP Lab F4A2 Status` remains because all tested API removal forms
were no-ops.

Monitoring callbacks (`onChanged`, `onBlockChanged`) cannot be transported as
ordinary request/response HTTP calls and remain unavailable. Block, tag, icon,
and file operations not listed as tools remain unexposed until they pass
write/read-back/cleanup testing.

## Tests

```powershell
python -m pytest -q
```