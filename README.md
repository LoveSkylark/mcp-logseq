# MCP Server for LogSeq

![MCP LogSeq logo](assets/images/logo.png)

Connect Claude to your LogSeq knowledge base. Read, create, and manage pages
with optional semantic vector search and DB-mode graph support.

This repository is now a substantially expanded derivative of the original
[ergut/mcp-logseq project](https://github.com/ergut/mcp-logseq). See
[Project Derivation](PROJECT_DERIVATION.md) for the original design and
structure, the implemented changes, and current limitations.

> [!WARNING]
> **This MCP can change or delete your Logseq data.** Depending on the graph
> mode and enabled tools, an AI connected to this server may create, edit,
> move, or delete pages, blocks, tags, properties, and related graph content.
> Use it only with a graph you have backed up, review proposed changes, and
> grant permission deliberately. AI clients often ask for confirmation before
> destructive actions, but permission prompts are not guaranteed by this MCP.

##  What You Can Do

Transform your LogSeq knowledge base into an AI-powered workspace. This MCP
server enables Claude to read, organize, and safely update your LogSeq graphs.

### Core Capabilities

- **Graph-aware workflows**: dedicated Claude Desktop skills keep DB-node and
  Markdown/file-graph instructions separate.
- **Safe DB batches**: validate related DB page, block, tag, and property
  changes before committing them with `upsert_nodes`.
- **Focused editing**: inspect pages and blocks, draft a minimal change plan,
  then verify the result after every significant update.
- **Privacy controls**: hide excluded tags and namespaces from listings, search,
  direct reads, and vector retrieval.
- **Bounded responses**: search limits, read deadlines, and response budgets
  keep large graphs from overwhelming an MCP conversation.
- **Optional semantic search**: find related notes by meaning with local or
  hosted embedding providers.

###  Real-World Examples

####  Intelligent Knowledge Management

```text
"Analyze all my project notes from the past month and create a status summary"
"Find pages mentioning 'machine learning' and create a study roadmap"
"Search for incomplete tasks across all my pages"
```

####  Automated Content Creation

```text
"Create a new page called 'Today's Standup' with my meeting notes"
"Add today's progress update to my existing project timeline page"
"Create a weekly review page from my recent notes"
```

####  Smart Research & Analysis

```text
"Compare my notes on React vs Vue and highlight key differences"
"Find all references to 'customer feedback' and summarize themes"
"Create a knowledge map connecting related topics across pages"
```

####  Semantic Search *(optional, requires vector setup)*

```text
"Find everything I wrote about burnout, even if I didn't use that word"
"What notes relate to my thoughts on deep work?"
"Search across my Dutch and English notes for ideas about productivity"
```

####  Meeting & Documentation Workflow

```text
"Read my meeting notes and create individual task pages for each action item"
"Get my journal entries from this week and create a summary page"
"Search for 'Q4 planning' and organize all related content into a new overview page"
```

###  Key Benefits

- **Zero Context Switching**: Claude works directly with your LogSeq data.
- **Preserve Your Workflow**: No need to export or copy content manually.
- **Graph-Specific Guidance**: DB and file graphs each receive the right tools,
  markup rules, and write workflow.
- **Safer Automation**: DB batches preflight before commit, and read responses
  stay bounded for large graphs.
- **Semantic Vector Search** *(optional)*: Find notes by meaning using local
  Ollama or hosted OpenAI-compatible embeddings.

---

##  Quick Start

### Step 1: Enable LogSeq API

1. **Settings**  **Features**  Check "Enable HTTP APIs server"
2. Click the **API button ()** in LogSeq  **"Start server"**
3. **Generate API token**: API panel  "Authorization tokens"  Create new

### Step 2: Install and Connect the MCP

See **[INSTALLATION.md](INSTALLATION.md)** for complete setup instructions
for Claude Code, Claude Desktop, and ChatGPT, both from a local checkout and
directly from GitHub. The guide also explains the `uv` commands, cache
behavior, graph mode, remote HTTP deployment, and verification.

#### Claude Desktop skills

Choose exactly one mode-specific skill and its matching MCP configuration. Do
not import both skills into the same conversation.

| Graph type | Skill and configuration |
| --- | --- |
| Logseq 2.x DB graph | [DB graph skill](skills/logseq-db-graph/README.md) with `LOGSEQ_DB_MODE=true` |
| Legacy Markdown/file graph | [File graph skill](skills/logseq-file-graph/README.md) with `LOGSEQ_DB_MODE=false` |

The skills contain the safe read/write workflow, markup rules, schema details,
and the exact Claude Desktop configuration. Use `LOGSEQ_DB_MODE=true` or
`false` for normal deployments. The legacy `auto` value is retained only for
non-skill deployments that intentionally support both graph types.

### Step 3: Start Using

```text
"Please help me organize my LogSeq notes. Show me what pages I have."
```

### Choose a Graph Mode

`LOGSEQ_DB_MODE=true` forces the DB-native API path. `false` forces the legacy
Markdown/file path. Use one of these explicit values for Claude Desktop and
Claude Code. The legacy `auto` value detects the active graph and retains the
full tool catalog only for deployments intentionally supporting both graph
types; it is not valid for either dedicated graph skill.

Read-only tools stop after `MCP_READ_TOOL_TIMEOUT` seconds (default `90`), and
their output is capped by `MCP_MAX_RESPONSE_CHARS` (default `30000`). Set the
response value to `0` only when an unbounded read is intentional.

The MCP process reuses one HTTP client and connection pool for each endpoint,
token, and graph-mode configuration. DB vector indexing reads through Logseq's
API and requires `LOGSEQ_API_TOKEN`; do not point file-based vector sync at a
DB graph.

---

##  Vector Search (Optional)

Semantic search over your Logseq graph using configurable embeddings. Find notes
by meaning, not just keywords, across pages using vector similarity and full-text
search with cross-language support.

Use [Ollama](https://ollama.com) for fully local embeddings, OpenAI, or another OpenAI-compatible embeddings endpoint. [LanceDB](https://lancedb.com) remains local in every configuration. Hosted providers receive the note text being embedded.

 **[Full setup guide: VECTOR_SEARCH.md](VECTOR_SEARCH.md)**

---

##  Available Tools

The server provides 39 verified standard tools, grouped by graph type, plus 3 optional vector tools.

### API Connection Points

The service connects to Logseq through these API namespaces:

1. **`logseq.Editor.*`**: page, block, property, and tag operations for the
  legacy file-graph adapter. File graphs use this exclusively.
2. **`logseq.cli.*` and `logseq.DB.*`**: DB-native page discovery, supported
  operations, batch node mutations, and safe Datascript-backed block reads.
  DB graphs also use `logseq.app.*` for search. They never fall back to
  `logseq.Editor.*`; an operation with no safe DB route is unavailable rather
  than silently using the file-graph API. See [Tool Availability by Graph Type](#tool-availability-by-graph-type).

DB search uses the companion **`logseq.app.search`** endpoint.

The complete API contract, including the static DB CLI export table, namespace
aliases, and native MCP mappings, is maintained in
[LOGSEQ_API_ARCHITECTURE.md](LOGSEQ_API_ARCHITECTURE.md). The DB skill is the
operational source of truth for safe tool selection and batching.

### File Graph and DB Graph Differences

| Area | File graph | DB graph |
| --- | --- | --- |
| Storage | Markdown files in `pages/` and `journals/` | SQLite/DataScript graph |
| Identity | Page names and block UUIDs | Node UUIDs and numeric `db/id` values |
| Content field | Markdown/block `content` | Namespaced `block/title` |
| Properties | `key:: value` lines | Typed property entities and `logseq.property/*` fields |
| Tags | Text tags in Markdown properties | First-class tag/class nodes |
| Main write pattern | Individual `logseq.Editor.*` operations | `logseq.cli.upsertNodes` batch operations |
| Page read pattern | `getPage` plus `getPageBlocksTree` | `logseq.cli.getPageData` for page-level blocks |
| Search pattern | `logseq.App.search` | `logseq.app.search` |

### Same Capability, Different API Namespace

Several MCP capabilities exist in both deployments, but they are backed by
different Logseq APIs. File graphs use `logseq.Editor.*` exclusively; DB
graphs use `logseq.DB.*`, `logseq.cli.*`, and `logseq.app.*` by operation. The MCP tool name is
not the same thing as the Logseq API method name.

| Capability | File graph tool and API | DB graph tool and API |
| --- | --- | --- |
| List pages | `list_pages` -> `logseq.Editor.getAllPages` | `list_pages` -> `logseq.cli.listPages` |
| Read page-level blocks | `get_page_content` -> `getPage` + `getPageBlocksTree` | `get_page_data` -> `logseq.cli.getPageData` |
| Find content | `search` -> `logseq.App.search` | `search_blocks` -> `logseq.app.search` |
| Read a block/tree | `get_block` -> `logseq.Editor.getBlock` | `get_block` -> bulk `logseq.DB.datascriptQuery` |
| Create or edit nodes | page/block `Editor.*` tools | `upsert_nodes` -> `logseq.cli.upsertNodes` |
| Read tags | page properties / `Editor.*` compatibility behavior | `list_tags` -> `logseq.cli.listTags` |
| Read properties | Markdown properties / `Editor.*` compatibility behavior | `list_properties` -> `logseq.cli.listProperties` |

When the graph is DB-based, prefer the DB column in this table. DB graphs use
`logseq.DB.*`, `logseq.cli.*`, and `logseq.app.*` by operation - there is no fallback to
`logseq.Editor.*`, so an operation with no verified `cli.*` route is simply
unavailable rather than silently using the file-graph API. See
[Tool Availability by Graph Type](#tool-availability-by-graph-type) below for
exactly which ones that affects, and prefer `upsert_nodes` for DB writes.

### Tool Availability by Graph Type

A tool is only registered when `LOGSEQ_DB_MODE` is forced to `true` or
`false`; in the default `auto` mode every tool below is registered and an
unsupported one fails at call time with an "available only for..." /
"not available for Logseq DB graphs" message.

DB graphs use `logseq.DB.*`, `logseq.cli.*`, and `logseq.app.*` by operation - there is **no fallback** to
`logseq.Editor.*` when a `cli.*` route hangs or errors. `Editor.*` writes can
wedge after several calls in one session and need a Logseq restart to
recover - see the note below the table before concluding a route is broken
from a single test.

| Tool | File | DB |
| --- | :---: | :---: |
| `upsert_nodes` | | ✅ |
| `get_page_data` | | ✅ |
| `list_tags` | | ✅ |
| `list_properties` | | ✅ |
| `search_blocks` | | ✅ |
| `get_property` | | ✅ |
| `upsert_property` | | ✅ |
| `remove_property` | | ✅ |
| `get_block_properties` | | ✅ |
| `get_block_property` | | ✅ |
| `upsert_block_property` | | ✅ |
| `remove_block_property` | | ✅ |
| `get_tag` | | ✅ |
| `get_tag_objects` | | ✅ |
| `get_tags_by_name` | | ✅ |
| `create_tag` | | ✅ |
| `add_block_tag` | | ✅ |
| `remove_block_tag` | | ✅ |
| `add_tag_property` | | ✅ |
| `remove_tag_property` | | ✅ |
| `add_tag_extends` | | ✅ |
| `remove_tag_extends` | | ✅ |
| `create_page` | ✅ | ✅ |
| `update_page` | ✅ | |
| `list_pages` | ✅ | ✅ |
| `get_page_content` | ✅ | ✅ |
| `delete_page` | ✅ | ✅ |
| `delete_block` | ✅ | ✅ |
| `update_block` | ✅ | ✅ |
| `get_block` | ✅ | ✅ |
| `search` | ✅ | ✅ |
| `query` | ✅ | |
| `find_pages_by_property` | ✅ | |
| `get_pages_from_namespace` | ✅ | |
| `get_pages_tree_from_namespace` | ✅ | |
| `rename_page` | ✅ | ✅ |
| `get_page_backlinks` | ✅ | |
| `insert_nested_block` | ✅ | |
| `set_block_properties` | | ✅ |
| `vector_search` ⚗️ | ✅ | ✅ |
| `sync_vector_db` ⚗️ | ✅ | ✅ |
| `vector_db_status` ⚗️ | ✅ | ✅ |

- **✅**: works in both graph modes, or is DB-native and works in DB mode.
- **`Editor.*` writes can wedge after repeated calls in one session** and
  need a Logseq restart to recover - a hang during testing does not always
  mean a route is broken. `delete_block` was initially misclassified as
  unavailable for exactly this reason: repeated failed attempts in one
  session wedged the write path, and re-testing the same session kept
  reproducing the wedge rather than the route's real (working) behavior. A
  route is only genuinely rejected if it still fails on a fresh restart.

DB `get_block` does not call either native `getBlock` endpoint. It uses one
bulk `logseq.DB.datascriptQuery` snapshot and builds the requested tree in
memory. `get_page_data` uses the same reader when `expand_children` is true,
which is the default. This avoids the Logseq 2.0.1 `getBlock` timeout path.

### Detailed Tool Guidance

The two skills are the authoritative tool and workflow guides:

- [File graph skill](skills/logseq-file-graph/SKILL.md): Markdown,
  namespaces, file properties, and Editor-backed operations.
- [DB graph skill](skills/logseq-db-graph/SKILL.md): UUIDs, typed
  properties, safe DB reads, dry-run validation, and `upsert_nodes` batches.

For the full API surface and Logseq 2.0.1 namespace behavior, see
[LOGSEQ_API_ARCHITECTURE.md](LOGSEQ_API_ARCHITECTURE.md).

### Optional Vector Tools

| Tool | Purpose |
| --- | --- |
| **`vector_search`**  | Semantic search by meaning |
| **`sync_vector_db`**  | Point to the external vector sync writer |
| **`vector_db_status`**  | Show vector DB health and staleness |

⚗️ *Requires vector search setup. See [VECTOR_SEARCH.md](VECTOR_SEARCH.md).*

For detailed DB batch operations, dry-run validation, Markdown parsing, and
safe retry rules, use the matching graph skill rather than duplicating those
workflows in this overview.

---

##  Prerequisites

Logseq must be running with its HTTP API server enabled and an API token. See
[Quick Start](#-quick-start) for the setup sequence.

### System Requirements

- **[uv](https://docs.astral.sh/uv/)** Python package manager
- **MCP-compatible client** (Claude Code, Claude Desktop, etc.)

---

##  Configuration

### Environment Variables

- **`LOGSEQ_API_TOKEN`** (required): Your LogSeq API token
- **`LOGSEQ_API_URL`** (optional): Server URL (default: `http://localhost:12315`)
- **`LOGSEQ_VERIFY_SSL`** (optional): Set to `false` only for trusted development certificates; HTTPS verifies certificates by default
- **`LOGSEQ_API_CONNECT_TIMEOUT`** (optional): HTTP connect timeout in seconds (default: `3`)
- **`LOGSEQ_API_READ_TIMEOUT`** (optional): HTTP read timeout in seconds (default: `6`)
- **`LOGSEQ_DB_MODE`** (optional): Defaults to `auto` and detects the active graph. Set to `true` to force DB mode or `false` to force legacy Markdown/file mode.
- **`MCP_READ_TOOL_TIMEOUT`** (optional): Total deadline in seconds for read-only MCP tools (default: `90`). Write tools retain their Logseq HTTP timeout because their completion can be ambiguous.
- **`MCP_MAX_RESPONSE_CHARS`** (optional): Maximum characters returned by a read tool before a response is truncated (default: `30000`; set to `0` to disable). Prefer per-tool `limit` and depth controls for predictable result shapes.
- **`LOGSEQ_EXCLUDE_TAGS`** (optional): Comma-separated tags. Pages with these tags are hidden from all tools. See [Privacy and Access Control](#privacy-and-access-control) below.
- **`LOGSEQ_INCLUDE_NAMESPACES`** (optional): Comma-separated namespace allow-list (e.g. `work,projects`). When set, **only** pages in these namespaces and their sub-pages are accessible. Everything else, including top-level pages without a namespace, is hidden from listings/search and denied on direct access. See [Privacy and Access Control](#privacy-and-access-control) below.
- **`LOGSEQ_EXCLUDE_NAMESPACES`** (optional): Comma-separated namespace deny-list (e.g. `finance,work/secret`). These namespaces are always blocked, taking priority over the include list. See [Privacy and Access Control](#privacy-and-access-control) below.
- **`LOGSEQ_CONFIG_FILE`** (optional): Path to a shared JSON config file holding the graph path, ACL defaults, and the `vector` block. Env vars (`LOGSEQ_EXCLUDE_TAGS`, `LOGSEQ_INCLUDE_NAMESPACES`, `LOGSEQ_EXCLUDE_NAMESPACES`) override the matching keys in this file.
- **`MCP_HTTP_AUTH_TOKEN`** (required for `--transport http`): Bearer token clients must send as `Authorization: Bearer <token>`. The server refuses to start in HTTP mode without it. See [Serving over HTTP](docs/SERVING.md).

For deployments where the assistant must not modify LogSeq, start the server with `--read-only`. This removes all page and block write tools while leaving read, search, and configured vector tools available. For remote HTTP deployments, use HTTPS or a TLS-terminating reverse proxy; plain HTTP is restricted to loopback unless `--insecure` is explicitly supplied.

### Privacy and Access Control

Pages tagged with excluded tags are completely hidden from AI. They will not
appear in listings, searches, or queries, and attempting to read them directly
returns an access-denied error.

**Quick setup via env var:**

```bash
LOGSEQ_EXCLUDE_TAGS=private,secret
```

**Via config file** (also used for [vector search](VECTOR_SEARCH.md)):

```json
{
  "logseq_graph_path": "/path/to/your/logseq/pages",
  "exclude_tags": ["private", "secret"]
}
```

Point to it with `LOGSEQ_CONFIG_FILE=/path/to/config.json`.

In your Logseq pages, tag any page you want to protect:

```text
tags:: private
```

The exclusion applies to all tools: `list_pages`, `get_page_content`, `search`,
`query`, and the optional vector search. If you also use vector search,
`exclude_tags` at the root is automatically merged into the vector index
exclusion list. Private pages are never embedded.

#### Namespace access control

You can restrict access to specific namespaces using `LOGSEQ_INCLUDE_NAMESPACES` and `LOGSEQ_EXCLUDE_NAMESPACES`.

**Include list (strict allow-list):** Only the listed namespaces and their sub-pages are visible; everything else is hidden.

```bash
LOGSEQ_INCLUDE_NAMESPACES=work,projects
```

**Exclude list (deny-list):** The listed namespaces are always blocked, even if they appear in the include list.

```bash
LOGSEQ_EXCLUDE_NAMESPACES=work/secret,finance
```

**Via config file:**

```json
{
  "include_namespaces": ["work", "projects"],
  "exclude_namespaces": ["work/secret", "finance"]
}
```

Matching is segment-based and case-insensitive: `work` matches `work` and `work/projects` but not `workshop`. The behavior mirrors `LOGSEQ_EXCLUDE_TAGS`: list/search results silently omit blocked pages; direct read, write, delete, and block operations return an access-denied error.

Access control is enforced at the **page** level and applied across every tool: list/search/query results omit blocked pages, direct page/block access and backlinks are denied, and vector search is filtered. Block-level results from `search` and `query` are resolved back to their owning page, so a block belonging to a restricted page is filtered out of those results too.

**Index-time namespace scoping (vector DB only).** The keys above are *query-time*: every page is embedded, and blocked ones are filtered out of each response. For the vector DB you can also scope at *index time*: decide which namespaces are embedded into the DB **at all** with `include_namespaces` / `exclude_namespaces` inside the `vector` block of the config file:

```json
{
  "vector": {
    "enabled": true,
    "include_namespaces": ["work"],
    "exclude_namespaces": ["work/secret"]
  }
}
```

This is global, shaping the shared DB for every consumer. It keeps unwanted content off disk entirely rather than filtering it on read, which is useful for secrets you never want embedded or for keeping the index small. Matching is segment-based and case-insensitive. Because it changes what the index contains, it takes effect only after a full re-index: `logseq-sync --rebuild`.

###  Serving over HTTP, multi-profile & TLS

By default the server speaks **stdio**: your client spawns it as a subprocess, and most users need nothing more. To serve **sandboxed or remote clients** over the network, `mcp-logseq` can run as a long-lived HTTP service with bearer auth, per-profile isolation, and TLS:

```bash
mcp-logseq --transport http --host 127.0.0.1 --port 12320 # requires MCP_HTTP_AUTH_TOKEN
```

The full deployment guide covers the server-side **security model**, the **per-profile multi-instance** pattern, the separate **`logseq-sync` writer**, and native **TLS** / reverse-proxy setup. See **[docs/SERVING.md](docs/SERVING.md)**. Non-loopback binds over plain HTTP are refused unless you supply TLS or pass `--insecure`.

### Alternative Setup Methods

#### Using .env file

```bash
# .env
LOGSEQ_API_TOKEN=your_token_here
LOGSEQ_API_URL=http://localhost:12315
```

#### System environment variables

```bash
export LOGSEQ_API_TOKEN=your_token_here
export LOGSEQ_API_URL=http://localhost:12315
```

---

##  Verification & Testing

### Test LogSeq Connection

```bash
uv run --project "<REPO_DIR>" python -c "
from mcp_logseq.logseq import LogSeq
api = LogSeq(api_key='your_token')
print(f'Connected! Found {len(api.list_pages())} pages')
"
```

### Verify MCP Registration

```bash
claude mcp list  # Should show mcp-logseq
```

### Debug with MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv run --project "<REPO_DIR>" mcp-logseq
```

---

##  Troubleshooting

### Common Issues

#### "LOGSEQ_API_TOKEN environment variable required"

-  Enable HTTP APIs in **Settings  Features**
-  Click ** button**  **"Start server"** in LogSeq
-  Generate token in **API panel  Authorization tokens**
-  Verify token in your configuration

#### "spawn uv ENOENT" (Claude Desktop)

Claude Desktop can't find `uv`. Use the full path:

```bash
which uv  # Find your uv location
```

Update config with full path:

```json
{
  "mcpServers": {
    "mcp-logseq": {
      "command": "/Users/username/.local/bin/uv",
      "args": ["run", "--with", "mcp-logseq", "mcp-logseq"],
      "env": { "LOGSEQ_API_TOKEN": "your_token_here" }
    }
  }
}
```

**Common uv locations:**

- Curl install: `~/.local/bin/uv`
- Homebrew: `/opt/homebrew/bin/uv`
- Pip install: Check with `which uv`

#### Connection Issues

-  Confirm LogSeq is running
-  Verify API server is **started** (not just enabled)
-  Check port 12315 is accessible
-  Test with verification command above

---

##  Development

For local development, testing, and contributing, see **[DEVELOPMENT.md](DEVELOPMENT.md)**.

### Project Structure

```text
src/mcp_logseq/
 server.py          # MCP server setup, tool registration, read-only/profile handling
 settings.py         # Environment/config-file settings loader
 access.py           # Namespace/tag access-control policy and enforcement
 namespace.py         # Namespace matching helpers
 parser.py           # Markdown <-> Logseq block parsing (file graphs)
 transport/          # HTTP transport (auth, streaming)
 vector/              # Optional semantic search (embedder, db, sync, index)
 bin/                 # logseq-sync CLI entry point
 logseq/              # LogSeq HTTP API client, split into mixins by area:
    __init__.py         #   GRAPH_OPERATION_ROUTES, LogSeq class composition
    pages.py            #   PageMixin  - page CRUD, namespaces, backlinks
    blocks.py           #   BlockMixin - block CRUD, batch/nested insert
    properties.py       #   PropertyMixin - DB properties, datascript queries
    tags.py             #   TagMixin - DB tag/class operations
    search.py           #   SearchMixin - search, DSL query, upsert_nodes
 tools/                # MCP tool handlers, split by domain:
     __init__.py         #   Shared state, ToolHandler/_DBToolHandler bases, re-exports
     pages.py            #   Page tool handlers
     blocks.py            #   Block tool handlers
     search.py             #   search/query/find_pages_by_property
     db_native.py          #   upsert_nodes, get_page_data, list_tags/properties
     properties.py         #   DB property tool handlers
     tags.py               #   DB tag tool handlers
```

`logseq/` is the API client (one `LogSeq` class per graph mode); `tools/`
is the MCP-facing layer that wraps it with validation, access control, and
response formatting. See [LOGSEQ_API_ARCHITECTURE.md](LOGSEQ_API_ARCHITECTURE.md)
for the `logseq.Editor.*` (file graph) vs `logseq.cli.*`/`logseq.app.*`
(DB graph) routing policy those two packages implement.

---

**Ready to supercharge your LogSeq workflow with AI?**

**Star this repository** if you find it helpful.
