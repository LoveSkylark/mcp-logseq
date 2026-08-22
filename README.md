<div align="center">
  <img src="assets/images/logo.png" alt="MCP LogSeq" width="200" height="200">
  <h1>MCP server for LogSeq</h1>
  <p>Connect Claude to your LogSeq knowledge base. Read, create, and manage pages — with optional semantic vector search and DB-mode graph support.</p>
</div>

## ✨ What You Can Do

Transform your LogSeq knowledge base into an AI-powered workspace! This MCP server enables Claude to seamlessly interact with your LogSeq graphs.

### 🎯 Real-World Examples

**📊 Intelligent Knowledge Management**
```
"Analyze all my project notes from the past month and create a status summary"
"Find pages mentioning 'machine learning' and create a study roadmap"
"Search for incomplete tasks across all my pages"
```

**📝 Automated Content Creation**
```
"Create a new page called 'Today's Standup' with my meeting notes"
"Add today's progress update to my existing project timeline page"  
"Create a weekly review page from my recent notes"
```

**🔍 Smart Research & Analysis**
```
"Compare my notes on React vs Vue and highlight key differences"
"Find all references to 'customer feedback' and summarize themes"
"Create a knowledge map connecting related topics across pages"
```

**🧠 Semantic Search** *(optional, requires vector setup)*
```
"Find everything I wrote about burnout, even if I didn't use that word"
"What notes relate to my thoughts on deep work?"
"Search across my Dutch and English notes for ideas about productivity"
```

**🤝 Meeting & Documentation Workflow**
```
"Read my meeting notes and create individual task pages for each action item"
"Get my journal entries from this week and create a summary page"
"Search for 'Q4 planning' and organize all related content into a new overview page"
```

### 💡 Key Benefits
- **Zero Context Switching**: Claude works directly with your LogSeq data
- **Preserve Your Workflow**: No need to export or copy content manually
- **Intelligent Organization**: AI-powered page creation, linking, and search
- **Enhanced Productivity**: Automate repetitive knowledge work
- **Semantic Vector Search** *(optional)*: Find notes by meaning using local Ollama or hosted OpenAI-compatible embeddings
- **DB-mode Support** *(opt-in)*: Read and write class properties on Logseq DB-mode graphs

---

## 🚀 Quick Start

### Step 1: Enable LogSeq API
1. **Settings** → **Features** → Check "Enable HTTP APIs server"
2. Click the **API button (🔌)** in LogSeq → **"Start server"**
3. **Generate API token**: API panel → "Authorization tokens" → Create new

### Step 2: Add to Claude (No Installation Required!)

#### Claude Code
```bash
claude mcp add mcp-logseq \
  --env LOGSEQ_API_TOKEN=your_token_here \
  --env LOGSEQ_API_URL=http://localhost:12315 \
  --env LOGSEQ_API_CONNECT_TIMEOUT=10 \
  --env LOGSEQ_API_READ_TIMEOUT=60 \
  -- uv run --with mcp-logseq mcp-logseq
```

#### Claude Desktop
Add to your config file (`Settings → Developer → Edit Config`):
```json
{
  "mcpServers": {
    "mcp-logseq": {
      "command": "uv",
      "args": ["run", "--with", "mcp-logseq", "mcp-logseq"],
      "env": {
        "LOGSEQ_API_TOKEN": "your_token_here",
        "LOGSEQ_API_URL": "http://localhost:12315",
        "LOGSEQ_API_CONNECT_TIMEOUT": "10",
        "LOGSEQ_API_READ_TIMEOUT": "60"
      }
    }
  }
}
```

### Step 3: Start Using!
```
"Please help me organize my LogSeq notes. Show me what pages I have."
```

### LogSeq 2.x DB Graphs

For the LogSeq 2.0.1 DB version, set `LOGSEQ_DB_MODE=auto` or `true`. In `auto`
mode the server asks LogSeq which graph format is active. DB-mode reads use
LogSeq's native `logseq.cli.getPageData` and `logseq.app.search` APIs, while
bulk edits use `logseq.cli.upsertNodes`. The LogSeq desktop application must be
running with its HTTP API enabled and an API token configured.

The legacy Markdown/file graph path remains available when detection returns
false, or when `LOGSEQ_DB_MODE=false` is set explicitly. Do not point file-based vector sync at a DB graph: DB vector indexing
reads page data through the API and requires `LOGSEQ_API_TOKEN` in the sync
process environment.

The MCP process maintains one reusable HTTP API client and connection pool for
the configured LogSeq endpoint. Tool calls reuse that client session instead of
opening a new HTTP session for every operation. A different endpoint, token,
or graph mode creates a separate client configuration.

### Deployment Examples

#### Legacy File Graph

Set `LOGSEQ_DB_MODE=false` to force file mode. The server uses Markdown pages and
the file-graph `Editor.*` compatibility APIs:

```bash
LOGSEQ_API_TOKEN=your_token_here \
LOGSEQ_API_URL=http://localhost:12315 \
LOGSEQ_API_CONNECT_TIMEOUT=10 \
LOGSEQ_API_READ_TIMEOUT=60 \
mcp-logseq
```

#### LogSeq 2.0.1 DB Graph

Set DB mode to `true` when you know the active graph is a DB graph. DB tools use
UUIDs, typed properties, tags/classes, and the native `logseq.cli.*` APIs:

```bash
LOGSEQ_API_TOKEN=your_token_here \
LOGSEQ_API_URL=http://localhost:12315 \
LOGSEQ_DB_MODE=true \
LOGSEQ_API_CONNECT_TIMEOUT=10 \
LOGSEQ_API_READ_TIMEOUT=60 \
mcp-logseq
```

Use `LOGSEQ_DB_MODE=auto` when the same deployment may open either graph type.
Timeout values are seconds. Empty values such as `LOGSEQ_API_READ_TIMEOUT=""`
fall back to the default 6-second read timeout; use a numeric value such as
`60` for slower DB operations.

---

## 🔬 Vector Search (Optional)

Semantic search over your Logseq graph using configurable embeddings — find notes by meaning, not just keywords. Searches across all your pages using vector similarity and full-text search combined, with cross-language support.

Use [Ollama](https://ollama.com) for fully local embeddings, OpenAI, or another OpenAI-compatible embeddings endpoint. [LanceDB](https://lancedb.com) remains local in every configuration. Hosted providers receive the note text being embedded.

→ **[Full setup guide: VECTOR_SEARCH.md](VECTOR_SEARCH.md)**

---

## 🛠️ Available Tools

The server provides 42 standard tools, grouped by graph type, plus 3 optional vector tools.

### File Graph Tools

These tools support the original Markdown/file version of Logseq. They remain
available as compatibility tools when working with file graphs.

| Tool | Purpose |
|------|---------|
| **`list_pages`** | Browse pages |
| **`get_page_content`** | Read page content |
| **`create_page`** | Create pages with structured Markdown blocks |
| **`update_page`** | Append or replace page content |
| **`delete_page`** | Delete a page |
| **`delete_block`** | Delete a block by UUID |
| **`update_block`** | Update block content by UUID |
| **`get_block`** | Read a block and its children |
| **`search`** | Search graph content |
| **`query`** | Execute Logseq DSL queries |
| **`find_pages_by_property`** | Find pages by property |
| **`get_pages_from_namespace`** | List pages in a namespace |
| **`get_pages_tree_from_namespace`** | Show a namespace hierarchy |
| **`rename_page`** | Rename a page and update references |
| **`get_page_backlinks`** | Find pages linking to a page |
| **`insert_nested_block`** | Insert child or sibling blocks |

### DB Graph Tools

These tools use Logseq 2.x DB APIs, UUIDs, typed properties, tags/classes, and
DB node relationships. Enable them with `LOGSEQ_DB_MODE=true` or
`LOGSEQ_DB_MODE=auto`.

| Tool | Purpose |
|------|---------|
| **`upsert_nodes`** | Batch-create or edit pages, blocks, tags, and properties |
| **`get_page_data`** | Read a DB page entity and block tree |
| **`list_tags`** | List tags/classes |
| **`list_properties`** | List typed property definitions |
| **`search_blocks`** | Search DB blocks by content |
| **`get_property`** | Read a property definition |
| **`upsert_property`** | Create or update a typed property |
| **`remove_property`** | Remove a property definition |
| **`get_block_properties`** | Read all properties on a DB node |
| **`get_block_property`** | Read one property from a DB node |
| **`upsert_block_property`** | Set a typed property on a DB node |
| **`remove_block_property`** | Remove a property from a DB node |
| **`get_tag`** | Read a tag/class |
| **`get_tag_objects`** | List nodes carrying a tag/class |
| **`get_tags_by_name`** | Find tags by name |
| **`create_tag`** | Create a tag/class |
| **`add_block_tag`** | Add a tag to a DB node |
| **`remove_block_tag`** | Remove a tag from a DB node |
| **`list_nodes`** | List DB nodes with native options |
| **`list_tasks`** | List task nodes |
| **`list_assets`** | List asset nodes |
| **`add_tag_property`** | Add a property to a tag/class |
| **`remove_tag_property`** | Remove a property from a tag/class |
| **`add_tag_extends`** | Add a parent class to a tag |
| **`remove_tag_extends`** | Remove a parent class from a tag |
| **`set_block_properties`** | Set DB class properties on a node |

### Optional Vector Tools

| Tool | Purpose |
|------|---------|
| **`vector_search`** ⚗️ | Semantic search by meaning |
| **`sync_vector_db`** ⚗️ | Point to the external vector sync writer |
| **`vector_db_status`** ⚗️ | Show vector DB health and staleness |

⚗️ *Requires vector search setup — see [VECTOR_SEARCH.md](VECTOR_SEARCH.md)*

### Batch Changes in DB Mode

The DB-mode `upsert_nodes` tool accepts an array of operations in one request.
Logseq validates and applies that batch through its DB/outliner layer, so one
call can create or edit several pages, blocks, tags, and properties without a
separate round trip for every change. This is faster and keeps related changes
together while avoiding partially stale results between individual requests.

For example, a new page and a block on that page can be sent together by giving
the page a temporary ID and referring to it from the block:

```json
{
  "operations": [
    {
      "operation": "add",
      "entityType": "page",
      "id": "temp-inbox",
      "data": {"title": "Inbox"}
    },
    {
      "operation": "add",
      "entityType": "block",
      "data": {"page-id": "temp-inbox", "title": "Review proposal"}
    }
  ],
  "dry_run": false
}
```

Use `dry_run: true` to run Logseq's validation without committing changes.
Prefer one well-formed batch per user request; use UUIDs for existing nodes and
temporary IDs only for new nodes referenced by later operations.

### 🎨 Smart Markdown Parsing (v1.1.0+)

The `create_page` and `update_page` tools now automatically convert markdown into Logseq's native block structure:

**Markdown Input:**
````markdown
---
tags: [project, active]
priority: high
---

# Project Overview
Introduction paragraph here.

## Tasks
- Task 1
  - Subtask A
  - Subtask B
- Task 2

## Code Example
```python
def hello():
    print("Hello Logseq!")
```
````

**Result:** Creates properly nested blocks with:
- ✅ Page properties from YAML frontmatter (`tags`, `priority`)
- ✅ Hierarchical sections from headings (`#`, `##`, `###`)
- ✅ Nested bullet lists with proper indentation
- ✅ Code blocks preserved as single blocks
- ✅ Checkbox support (`- [ ]` → TODO, `- [x]` → DONE)

**Update Modes:**
- **`append`** (default): Add new content after existing blocks
- **`replace`**: Clear page and replace with new content

### 🔁 Safe Retries & Large Writes

`create_page` fails with a clear error if a page with the same title already exists, instead of letting Logseq silently create numbered duplicates (`Page(1)`, `Page 2`, ...). This makes retries after a timeout safe: if a previous `create_page` call timed out but actually committed, the retry tells you the page exists rather than fragmenting your content across ghost pages.

For large writes, prefer this pattern over one giant `create_page` call:

1. Create the page with little or no content (`create_page` with just the title and properties)
2. Append content in smaller chunks with `update_page` (`mode: append`)
3. Read back with `get_page_content` to verify the result

If you hit the "already exists" error mid-ingest, use `get_page_content` to see what landed, then continue with `update_page` instead of re-creating.

---

## ⚙️ Prerequisites

### LogSeq Setup
- **LogSeq installed** and running
- **HTTP APIs server enabled** (Settings → Features)
- **API server started** (🔌 button → "Start server")  
- **API token generated** (API panel → Authorization tokens)

### System Requirements
- **[uv](https://docs.astral.sh/uv/)** Python package manager
- **MCP-compatible client** (Claude Code, Claude Desktop, etc.)

---

## 🔧 Configuration

### Environment Variables
- **`LOGSEQ_API_TOKEN`** (required): Your LogSeq API token
- **`LOGSEQ_API_URL`** (optional): Server URL (default: `http://localhost:12315`)
- **`LOGSEQ_VERIFY_SSL`** (optional): Set to `false` only for trusted development certificates; HTTPS verifies certificates by default
- **`LOGSEQ_API_CONNECT_TIMEOUT`** (optional): HTTP connect timeout in seconds (default: `3`)
- **`LOGSEQ_API_READ_TIMEOUT`** (optional): HTTP read timeout in seconds (default: `6`)
- **`LOGSEQ_DB_MODE`** (optional): Defaults to `auto` and detects the active graph. Set to `true` to force DB mode or `false` to force legacy Markdown/file mode.
- **`LOGSEQ_EXCLUDE_TAGS`** (optional): Comma-separated tags — pages with these tags are hidden from all tools. See [Privacy & Access Control](#-privacy--access-control) below.
- **`LOGSEQ_INCLUDE_NAMESPACES`** (optional): Comma-separated namespace allow-list (e.g. `work,projects`). When set, **only** pages in these namespaces and their sub-pages are accessible — everything else, including top-level pages without a namespace, is hidden from listings/search and denied on direct access. See [Privacy & Access Control](#-privacy--access-control) below.
- **`LOGSEQ_EXCLUDE_NAMESPACES`** (optional): Comma-separated namespace deny-list (e.g. `finance,work/secret`). These namespaces are always blocked, taking priority over the include list. See [Privacy & Access Control](#-privacy--access-control) below.
- **`LOGSEQ_CONFIG_FILE`** (optional): Path to a shared JSON config file holding the graph path, ACL defaults, and the `vector` block. Env vars (`LOGSEQ_EXCLUDE_TAGS`, `LOGSEQ_INCLUDE_NAMESPACES`, `LOGSEQ_EXCLUDE_NAMESPACES`) override the matching keys in this file.
- **`MCP_HTTP_AUTH_TOKEN`** (required for `--transport http`): Bearer token clients must send as `Authorization: Bearer <token>`. The server refuses to start in HTTP mode without it. See [Serving over HTTP](docs/SERVING.md).

For deployments where the assistant must not modify LogSeq, start the server with `--read-only`. This removes all page and block write tools while leaving read, search, and configured vector tools available. For remote HTTP deployments, use HTTPS or a TLS-terminating reverse proxy; plain HTTP is restricted to loopback unless `--insecure` is explicitly supplied.

### Privacy & Access Control

Pages tagged with excluded tags are completely hidden from AI — they won't appear in listings, searches, or queries, and attempting to read them directly returns an access-denied error.

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
```
tags:: private
```

The exclusion applies to all tools: `list_pages`, `get_page_content`, `search`, `query`, and the optional vector search. If you also use vector search, `exclude_tags` at the root is automatically merged into the vector index exclusion list — private pages are never embedded.

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

**Index-time namespace scoping (vector DB only).** The keys above are *query-time*: every page is embedded, and blocked ones are filtered out of each response. For the vector DB you can also scope at *index time* — decide which namespaces are embedded into the DB **at all** — with `include_namespaces` / `exclude_namespaces` inside the `vector` block of the config file:

```json
{
  "vector": {
    "enabled": true,
    "include_namespaces": ["work"],
    "exclude_namespaces": ["work/secret"]
  }
}
```

This is global (it shapes the shared DB for every consumer), and it keeps unwanted content off disk entirely rather than filtering it on read — useful for secrets you never want embedded, or to keep the index small when everyone only cares about a subset. Matching is the same segment-based, case-insensitive rule. Because it changes what the index contains, it only takes effect after a full re-index: `logseq-sync --rebuild`.

### 🌐 Serving over HTTP, multi-profile & TLS

By default the server speaks **stdio** — your client spawns it as a subprocess, and most users need nothing more. To serve **sandboxed or remote clients** over the network, `mcp-logseq` can run as a long-lived HTTP service with bearer auth, per-profile isolation, and TLS:

```bash
mcp-logseq --transport http --host 127.0.0.1 --port 12320   # requires MCP_HTTP_AUTH_TOKEN
```

The full deployment guide — the server-side **security model**, the **per-profile multi-instance** pattern, the separate **`logseq-sync` writer**, and native **TLS** / reverse-proxy setup — lives in **[docs/SERVING.md](docs/SERVING.md)**. Non-loopback binds over plain HTTP are refused unless you supply TLS or pass `--insecure`.


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

## 🔍 Verification & Testing

### Test LogSeq Connection
```bash
uv run --with mcp-logseq python -c "
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
npx @modelcontextprotocol/inspector uv run --with mcp-logseq mcp-logseq
```

---

## 🐛 Troubleshooting

### Common Issues

#### "LOGSEQ_API_TOKEN environment variable required"
- ✅ Enable HTTP APIs in **Settings → Features**
- ✅ Click **🔌 button** → **"Start server"** in LogSeq
- ✅ Generate token in **API panel → Authorization tokens**
- ✅ Verify token in your configuration

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
- ✅ Confirm LogSeq is running
- ✅ Verify API server is **started** (not just enabled)
- ✅ Check port 12315 is accessible
- ✅ Test with verification command above

---

## 👩‍💻 Development

For local development, testing, and contributing, see **[DEVELOPMENT.md](DEVELOPMENT.md)**.

---

<div align="center">
  <p><strong>Ready to supercharge your LogSeq workflow with AI?</strong></p>
  <p>⭐ <strong>Star this repo</strong> if you find it helpful!</p>
</div>
