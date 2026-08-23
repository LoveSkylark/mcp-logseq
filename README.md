# MCP Server for LogSeq

![MCP LogSeq logo](assets/images/logo.png)

Connect Claude to your LogSeq knowledge base. Read, create, and manage pages
with optional semantic vector search and DB-mode graph support.

## ✨ What You Can Do

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

### 🎯 Real-World Examples

#### 📊 Intelligent Knowledge Management

```text
"Analyze all my project notes from the past month and create a status summary"
"Find pages mentioning 'machine learning' and create a study roadmap"
"Search for incomplete tasks across all my pages"
```

#### 📝 Automated Content Creation

```text
"Create a new page called 'Today's Standup' with my meeting notes"
"Add today's progress update to my existing project timeline page"
"Create a weekly review page from my recent notes"
```

#### 🔍 Smart Research & Analysis

```text
"Compare my notes on React vs Vue and highlight key differences"
"Find all references to 'customer feedback' and summarize themes"
"Create a knowledge map connecting related topics across pages"
```

#### 🧠 Semantic Search *(optional, requires vector setup)*

```text
"Find everything I wrote about burnout, even if I didn't use that word"
"What notes relate to my thoughts on deep work?"
"Search across my Dutch and English notes for ideas about productivity"
```

#### 🤝 Meeting & Documentation Workflow

```text
"Read my meeting notes and create individual task pages for each action item"
"Get my journal entries from this week and create a summary page"
"Search for 'Q4 planning' and organize all related content into a new overview page"
```

### 💡 Key Benefits

- **Zero Context Switching**: Claude works directly with your LogSeq data.
- **Preserve Your Workflow**: No need to export or copy content manually.
- **Graph-Specific Guidance**: DB and file graphs each receive the right tools,
  markup rules, and write workflow.
- **Safer Automation**: DB batches preflight before commit, and read responses
  stay bounded for large graphs.
- **Semantic Vector Search** *(optional)*: Find notes by meaning using local
  Ollama or hosted OpenAI-compatible embeddings.

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
  --env MCP_READ_TOOL_TIMEOUT=90 \
  --env MCP_MAX_RESPONSE_CHARS=30000 \
  --env PYTHONIOENCODING=utf-8 \
  -- uv run --with mcp-logseq mcp-logseq
```

#### Claude Desktop

Choose exactly one mode-specific skill and its matching MCP configuration. Do
not import both skills into the same conversation.

| Graph type | Skill and configuration |
| --- | --- |
| Logseq 2.x DB graph | [DB graph skill](skills/claude-desktop-logseq-db/README.md) with `LOGSEQ_DB_MODE=true` |
| Legacy Markdown/file graph | [File graph skill](skills/claude-desktop-logseq-file/README.md) with `LOGSEQ_DB_MODE=false` |

The skills contain the safe read/write workflow, markup rules, schema details,
and the exact Claude Desktop configuration. Use `LOGSEQ_DB_MODE=auto` only for
non-skill deployments that intentionally support both graph types.

### Step 3: Start Using

```text
"Please help me organize my LogSeq notes. Show me what pages I have."
```

### Choose a Graph Mode

`LOGSEQ_DB_MODE=true` forces the DB-native API path. `false` forces the legacy
Markdown/file path. `auto` detects the active graph and retains the full tool
catalog for non-skill deployments.

Read-only tools stop after `MCP_READ_TOOL_TIMEOUT` seconds (default `90`), and
their output is capped by `MCP_MAX_RESPONSE_CHARS` (default `30000`). Set the
response value to `0` only when an unbounded read is intentional.

The MCP process reuses one HTTP client and connection pool for each endpoint,
token, and graph-mode configuration. DB vector indexing reads through Logseq's
API and requires `LOGSEQ_API_TOKEN`; do not point file-based vector sync at a
DB graph.

---

## 🔬 Vector Search (Optional)

Semantic search over your Logseq graph using configurable embeddings. Find notes
by meaning, not just keywords, across pages using vector similarity and full-text
search with cross-language support.

Use [Ollama](https://ollama.com) for fully local embeddings, OpenAI, or another OpenAI-compatible embeddings endpoint. [LanceDB](https://lancedb.com) remains local in every configuration. Hosted providers receive the note text being embedded.

→ **[Full setup guide: VECTOR_SEARCH.md](VECTOR_SEARCH.md)**

---

## 🛠️ Available Tools

The server provides 39 verified standard tools, grouped by graph type, plus 3 optional vector tools.

### API Connection Points

The service connects to Logseq through two primary API namespaces:

1. **`logseq.Editor.*`**: page, block, property, and tag operations. This is
  used by the legacy file-graph adapter and also exposes DB-capable individual
  node/property operations.
2. **`logseq.cli.*`**: Logseq 2.x DB-native page discovery, page data, and
  batch node operations. This is the preferred connection point for DB graphs.

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
| Page read pattern | `getPage` plus `getPageBlocksTree` | `logseq.cli.getPageData` |
| Search pattern | `logseq.App.search` | `logseq.app.search` |

### Same Capability, Different API Namespace

Several MCP capabilities exist in both deployments, but they are backed by
different Logseq APIs. File graphs use `logseq.Editor.*`; DB graphs prefer the
verified `logseq.cli.*` APIs and DB node operations. The MCP tool name is not
the same thing as the Logseq API method name.

| Capability | File graph tool and API | DB graph tool and API |
| --- | --- | --- |
| List pages | `list_pages` -> `logseq.Editor.getAllPages` | `list_pages` -> `logseq.cli.listPages` |
| Read a page tree | `get_page_content` -> `getPage` + `getPageBlocksTree` | `get_page_data` -> `logseq.cli.getPageData` |
| Find content | `search` -> `logseq.App.search` | `search_blocks` -> `logseq.app.search` |
| Read a block/tree | `get_block` -> `logseq.Editor.getBlock` | `get_page_data` for a page tree; no verified `logseq.cli.getBlock` endpoint |
| Create or edit nodes | page/block `Editor.*` tools | `upsert_nodes` -> `logseq.cli.upsertNodes` |
| Read tags | page properties / `Editor.*` compatibility behavior | `list_tags` -> `logseq.cli.listTags` |
| Read properties | Markdown properties / `Editor.*` compatibility behavior | `list_properties` -> `logseq.cli.listProperties` |

When the graph is DB-based, prefer the DB column in this table. Use
`logseq.cli.*` for the native DB MCP workflows, and use the verified DB-capable
`logseq.Editor.*` property/tag APIs for operations that do not have a CLI
equivalent.

### Detailed Tool Guidance

The two skills are the authoritative tool and workflow guides:

- [File graph skill](skills/claude-desktop-logseq-file/SKILL.md): Markdown,
  namespaces, file properties, and Editor-backed operations.
- [DB graph skill](skills/claude-desktop-logseq-db/SKILL.md): UUIDs, typed
  properties, safe DB reads, dry-run validation, and `upsert_nodes` batches.

For the full API surface and Logseq 2.0.1 namespace behavior, see
[LOGSEQ_API_ARCHITECTURE.md](LOGSEQ_API_ARCHITECTURE.md).

### Optional Vector Tools

| Tool | Purpose |
| --- | --- |
| **`vector_search`** ⚗️ | Semantic search by meaning |
| **`sync_vector_db`** ⚗️ | Point to the external vector sync writer |
| **`vector_db_status`** ⚗️ | Show vector DB health and staleness |

⚗️ *Requires vector search setup. See [VECTOR_SEARCH.md](VECTOR_SEARCH.md).*

For detailed DB batch operations, dry-run validation, Markdown parsing, and
safe retry rules, use the matching graph skill rather than duplicating those
workflows in this overview.

---

## ⚙️ Prerequisites

Logseq must be running with its HTTP API server enabled and an API token. See
[Quick Start](#-quick-start) for the setup sequence.

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

### 🌐 Serving over HTTP, multi-profile & TLS

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

**Ready to supercharge your LogSeq workflow with AI?**

⭐ **Star this repository** if you find it helpful.
