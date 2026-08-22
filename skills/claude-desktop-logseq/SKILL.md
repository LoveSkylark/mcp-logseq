---
name: logseq-mcp-writing
description: Reading and writing Logseq file graphs and Logseq 2.0.x DB graphs through the mcp-logseq MCP server. Prefer DB-native tools when graph detection reports a DB graph; use the file-graph tools for Markdown graphs. Covers setup, safe reads/writes, batching, access control, timeouts, and Logseq 2.0.x failure modes.
---

# Logseq over MCP: DB Preferred

Applies to **Logseq 2.0.1 DB graphs** and legacy **Logseq Markdown/file graphs** when
using **mcp-logseq 1.8.0**. The service defaults to `LOGSEQ_DB_MODE=auto`: detect
the active graph, prefer DB-native tools for DB graphs, and retain the Markdown
adapter for file graphs. Use `LOGSEQ_DB_MODE=true` or `false` only when the graph
type must be forced.

The DB-specific behavior below was verified by direct testing on 21 August 2026.

## Choose the graph mode

1. Start Logseq and enable its HTTP API server.
2. Configure `LOGSEQ_DB_MODE` as `auto` (recommended), `true` (DB graph), or
  `false` (legacy Markdown/file graph).
3. In `auto` mode, let the service detect the graph before choosing tools.
4. For DB graphs, prefer `get_page_data`, `search_blocks`, typed property/tag
  tools, and `upsert_nodes`. For file graphs, use `get_page_content`, `search`,
  `query`, and the page/block compatibility tools.

Do not send Markdown `key:: value` assumptions to DB tools. DB graphs use UUIDs,
numeric IDs, typed properties, tags/classes, and namespaced fields such as
`block/title` and `block/uuid`.

## DB-mode operational rules

The following hang and write-throughput warnings apply to Logseq 2.0.1 DB mode,
not automatically to legacy file graphs.

**Logseq 2.0.1 can hang instead of erroring when it dislikes an argument.**

A wrong *method name* returns HTTP 500 in 2ms. A wrong *argument shape* never responds at
all — the call sits until the client gives up.

So a timeout means **"wrong arguments"**, not "server down", "graph too big", or "tool
broken". Do not restart anything, do not chase processes, do not raise the timeout. Check
the call signature against the tables below.

The sharpest example: `get_block` with `include_children=false` **hangs forever**; with
`true` it returns in 3ms. Same tool, same block.

### DB throughput limit — the server wedges after a run of writes

**Logseq 2.0.1 wedges during rapid bursts of `Editor` writes.** Observed three separate times
in one session, each after a fast uninterrupted run, each recovering only after a full Logseq
restart.

**The trigger is the write count, not the rate.** Tested directly: after a clean restart,
7 writes succeeded, then every write from the 8th onward timed out — *with `search` calls
interleaved throughout*. Spacing did not raise the ceiling. Budget **about 7 writes per
Logseq restart** and plan the session around that.

**Timed-out writes usually still commit.** Of the timeouts observed after the ceiling was
hit, nearly all landed — sometimes not visible immediately, but present on a later check.
The timeout is a reporting failure, not necessarily a write failure. Always read back with
`search` before rewriting, and never assume a timeout meant nothing happened.

Symptoms of a wedge, in order:

1. Writes succeed normally
2. One write hangs to the timeout
3. Every subsequent `Editor` call hangs — reads included — while `search` keeps working
4. Nothing further commits until Logseq is restarted **and** a new MCP session is started

**Plan the work accordingly:**

- Budget **~7 writes per restart**; prepare the whole batch before spending any of them
- Treat the first unexplained hang as the ceiling, not something to retry through
- After a hang, verify with `search` — the write probably landed
- Then stop, restart Logseq, and continue

Recovery costs a Logseq restart, so the aim is to spend the budget on prepared edits rather
than discovering the ceiling mid-queue.

**On a hang, check before retrying.** Timed-out writes frequently *do* commit — verified
repeatedly. Use `search` (which survives the wedge) to read the block back. Retrying a write
that already landed is harmless, but assuming it failed and rewriting from stale content is
not.

### Prepare everything before writing anything

Because write capacity is the scarce resource, all lookup work belongs **before** the first
write, not interleaved with it.

**The wrong shape** — costs a restart halfway through:

```
search target A → update block 1 → search target B → update block 2 → …
```

**The right shape:**

1. **Enumerate the damage once.** One datascript call returns every block needing repair,
   with its UUID and current text (see Repairing broken links).
2. **Build a name → UUID table once.** Target pages repeat heavily across a graph — a handful
   of hubs account for most references. Resolve each one *once* with `search`, reading the
   `uuid` from the `pages` array, and reuse it for every block that mentions it. Many UUIDs
   can also be read straight out of the enumeration dump, since healthy refs already store
   them.
3. **Write the full replacement text for each block** — in the reply, before executing. This
   is also when contradictions get caught, while fixing them is still free.
4. **Only then execute**, in batches of five, verifying once per batch.

A repair session should be mostly reading and planning, with a short burst of writes at the
end. That ordering fits the throughput limit instead of fighting it, and it means an
interrupted session leaves a written queue that a later session can pick up directly.

### A hang with known-good arguments means the server is wedged

The argument rule above covers the *first* hang. There is a second failure mode with an
identical symptom and a different cause.

**One hung request poisons every subsequent Editor call.** Logseq's API handler appears to
serialise them, so a single unresolved promise blocks the whole path. `logseq.App.*` calls
(`search`, `list_pages`) use a different path and keep working — which makes the graph look
half-alive and is exactly what makes this confusing.

Tell the two apart by history, not by symptom:

| Situation | Meaning |
|---|---|
| Call has **never** worked this session | Wrong argument shape — check the signature |
| Call **worked earlier** with identical arguments, now hangs | Server wedged — restart |
| `search` works but every block call hangs | Server wedged — restart |

**After the first unexplained hang, stop.** Every Editor call after it will also hang, each
costing a full timeout, and none will commit. Do not retry, do not continue down a queue of
edits. Restart, then resume.

Read the curl timing carefully — three different failures look alike from inside MCP:

| curl result | Meaning |
|---|---|
| Block JSON in <1s | Logseq healthy. If MCP still hangs, **the MCP session is stale** — see below. |
| `HTTP 000` at ~2s (fails fast) | Nothing listening. App closed, or 🔌 server never started. |
| `HTTP 000` at the full timeout | Logseq wedged. Restart the app. |

**After Logseq restarts, the MCP session must restart too.** `mcp-logseq` pools its HTTP
connections (urllib3), and the pooled connections still point at the dead instance. The
signature is unmistakable: **curl returns in milliseconds while every MCP block call hangs.**
No amount of waiting fixes it — start a new conversation, which spawns a fresh server process.

Confirm it is Logseq rather than MCP with a direct curl:

```powershell
'{"method":"logseq.Editor.getBlock","args":["<known-block-uuid>",{"includeChildren":true}]}' | Set-Content -Path "$env:TEMP\q.json" -Encoding ascii -NoNewline
curl.exe -s -m 15 -w "`nHTTP %{http_code} in %{time_total}s`n" -X POST http://127.0.0.1:12315/api -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" --data-binary "@$env:TEMP\q.json"
```

### Restart procedure

1. 🔌 → **Stop server** (may not respond; continue regardless).
2. **Quit Logseq fully** — window *and* tray icon. Verify with
   `Get-Process | Where-Object { $_.ProcessName -match "Logseq" }`; force-kill if needed.
3. **Reopen and let the graph finish loading.** The DB version indexes on open; starting the
   API mid-index can wedge it again.
4. 🔌 → **Start server.** It does **not** auto-start, and a stopped server is
   indistinguishable from a wedged one.
5. **Verify with the curl above** before resuming work.
6. **Start a new Claude conversation.** MCP transports bind at session start, so the old chat
   stays broken even after Logseq recovers.

**Before restarting, write the outstanding queue into the conversation** — which blocks still
need repair, with their target UUIDs. The new session cannot see this one, and a written
queue is the only thing that survives.

### The general pattern

**Block-UUID-targeted calls work. Page-name and page-UUID-targeted calls hang.**

Logseq 2.0 unified pages and blocks into **nodes**, and the block-oriented paths are the
maintained ones. Anchor everything to a block UUID.

## Setup

### 1. Logseq

1. Settings → Features → enable **HTTP APIs server**.
2. Click the 🔌 button in the toolbar → **Start server**.
3. In the same panel → **Authorization tokens** → add a token.

**The API server does not survive a Logseq restart.** If every call fails at once, check
the 🔌 panel first — this is the most common cause of a total outage.

Default endpoint: `http://127.0.0.1:12315`.

### 2. uvx

`uvx` (from [uv](https://docs.astral.sh/uv/)) runs the server without a permanent install.

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Installs to `%USERPROFILE%\.local\bin\uvx.exe`. Verify:

```powershell
& "$env:USERPROFILE\.local\bin\uvx.exe" --version
```

Use the **absolute path** in the config below — a bare `uvx` often fails to resolve when
Claude Desktop launches the server.

### 3. claude_desktop_config.json

**The path depends on how Claude Desktop was installed.** For the Microsoft Store
package — the common case on Windows now — `%APPDATA%\Claude\` does **not** exist and the
real file is redirected into the package sandbox:

```
%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json
```

Locate it reliably rather than guessing:

```powershell
Get-ChildItem "$env:LOCALAPPDATA\Packages","$env:APPDATA" -Filter "claude_desktop_config.json" -Recurse -ErrorAction SilentlyContinue | Select-Object FullName
```

Or open it from inside the app: **Settings → Developer → Edit Config**.

```json
{
  "mcpServers": {
    "logseq": {
      "command": "C:\\Users\\YOU\\.local\\bin\\uvx.exe",
      "args": ["--with", "mcp<1.10", "mcp-logseq"],
      "env": {
        "LOGSEQ_API_TOKEN": "your-token",
        "LOGSEQ_API_URL": "http://127.0.0.1:12315",
        "LOGSEQ_DB_MODE": "auto",
        "LOGSEQ_API_CONNECT_TIMEOUT": "5",
        "LOGSEQ_API_READ_TIMEOUT": "10",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

Notes on each setting:

- `LOGSEQ_DB_MODE=auto` — recommended; detects DB versus file graph mode. Use
  `true` to force DB mode or `false` to force legacy Markdown/file mode.
- `LOGSEQ_API_READ_TIMEOUT=10` — keep it **low**. Nothing that hangs at 10s succeeds at 60s;
  a high value only makes failures slow.
- `PYTHONIOENCODING=utf-8` — prevents a `UnicodeEncodeError` crash when the server writes
  its ❌ emoji into a Windows cp1252 console stream.
- `--with mcp<1.10` — pins the MCP SDK the package expects.

**Quit Claude Desktop completely from the system tray before editing this file.** The app
holds config in memory and rewrites it on exit, silently discarding edits made while it is
running. Edit with the app closed, then relaunch.

### 4. Verify

```powershell
'{"method":"logseq.App.getCurrentGraph"}' | Set-Content -Path "$env:TEMP\q.json" -Encoding ascii -NoNewline
curl.exe -s -m 10 -w "`nHTTP %{http_code} in %{time_total}s`n" -X POST http://127.0.0.1:12315/api `
  -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" --data-binary "@$env:TEMP\q.json"
```

Expect graph JSON in well under a second.

When testing by curl on Windows, always write the body to a **file** with `-NoNewline` and
send it with `--data-binary`. Inline `-d` and here-strings add a trailing CRLF or mangle
escaping, and Logseq replies `FST_ERR_CTP_INVALID_JSON_BODY` — which looks like malformed
JSON when the JSON is fine. Always pass `-w` too: without it a hang and an empty result are
both blank output.

## File-graph tools

When detection reports a legacy Markdown/file graph, use the normal page and
block tools. File graphs store content in Markdown files and page properties as
`key:: value` lines.

### `get_page_content` — read a complete file-graph page

```
get_page_content(page_name="Project Notes", format="text")
```

Use `format="json"` when the page structure or properties must be inspected.
The file-graph path supports page names, nested Markdown blocks, journals, and
page properties.

### File-graph create and update

```
create_page(title="Meeting Notes", content="- Agenda\n- Decisions")
update_page(page_name="Meeting Notes", content="- Follow-up", mode="append")
```

Use `update_page` with `mode="replace"` only when replacing the whole page is
intentional. Use `update_block` and `insert_nested_block` when a UUID is
available and only one block needs changing.

### File-graph search and queries

```
search(query="customer feedback", format="json")
query(query="(page-property status active)", format="json")
```

For file graphs, page names and Markdown properties are the source of truth.
Do not use DB-only tools such as `upsert_nodes`, `list_tags`, or typed property
handlers when detection reports file mode.

## DB-mode tools that work

### `search` — the primary finder

Full-text across blocks and pages. Fast and reliable. **This is how you locate anything.**

```
search(query="Black Tide", format="json", limit=10)
```

Returns per hit: `uuid`, `title`, `content`, `id`, `parent`, `page` (the page's UUID), and
`page?: true` for page hits. `has_more` indicates truncation.

- `content` is clean text; `title`/`fullTitle` carry `$pfts_2lqh>$…$<pfts_2lqh$` search
  highlight markers — **read `content`, not `title`**.
- Because it returns UUIDs, `search` is the entry point for every edit: find the block,
  then act on its UUID.

### `get_block` — read a block and its subtree

```
get_block(block_uuid="6a84…", format="json", include_children=true)
```

**`include_children` must be `true`.** Passing `false` hangs the call.

Returns `content`, `title`, `uuid`, `id`, `order`, `parent`, `page`, timestamps, and a
`children` array containing fully-populated child blocks (each with its own `level`).
One call reads a whole subtree.

### `insert_nested_block` — create blocks

```
insert_nested_block(parent_block_uuid="6a84…", content="text", sibling=false)
```

- `sibling=false` → new block becomes a **child** of the target.
- `sibling=true` → new block becomes a **sibling** placed after the target.
- Returns the new block's UUID — capture it to nest further content underneath.

**The target must be a block UUID.** Passing a *page* UUID hangs.

To build a nested structure, insert the parent first, take the returned UUID, then insert
children against it. Depth is controlled entirely by which UUID you target.

### `update_block` — edit block text

```
update_block(block_uuid="6a84…", content="new text")
```

Replaces the block's content. This is the correct tool for a factual correction — never
rewrite a page to fix a sentence.

### `delete_block` — remove a block

```
delete_block(block_uuid="6a84…")
```

A **hard delete**, verified: the block disappears from its parent's `children` immediately.
Deleting a parent removes its subtree. There is no undo through MCP.

### `delete_page` — works, but see the deletion section before using

```
delete_page(page_name="zz scratch page")
```

Returns in milliseconds — it is **not** in the hanging page-targeted class. Its success
message claims the page was "permanently removed"; **this is false.** It is a soft delete,
and it damages every block that linked to the page. Read the deletion section below before
calling it.

### `query` — count and filter, using DB DSL

```
query(query="(property category \"Characters\")", format="json", limit=10)
```

Working filters:

| Filter | Example | Works |
|---|---|---|
| `(property KEY)` | `(property category)` | ✅ 110 results |
| `(property KEY "VALUE")` | `(property category "Characters")` | ✅ 24 results |
| `(has-property KEY)` | — | ❌ empty |
| `(task todo)` | — | ❌ empty |

Note DB renamed the file-graph filters: `(page-property)` → `(property)`,
`(page-tags)` → `(tags)`, `(priority A)` → `(priority high)`.

**Major limitation: `query` returns bare entity IDs (`{"id": 1132}`), not UUIDs or text.**
There is no way to resolve an `id` to a block through MCP. So `query` answers *"how many"*
and *"does any exist"* — for content, use `search`.

### `list_pages` — page inventory

Returns every page title, lowercased, plus a total. Includes property-definition pages
(`category`, `status`, `alias`…) alongside content pages, since properties are nodes too.
Useful for checking existence before creating; do not treat as live state.

### New DB-native handlers

Prefer these handlers in DB mode:

| Handler | Use |
|---|---|
| `get_page_data(page_name)` | Read a page entity and its complete DB block tree |
| `search_blocks(query)` | Search DB block titles/content and return node identifiers |
| `list_tags(expand=false)` | List DB tags/classes |
| `list_properties(expand=false)` | List typed DB property definitions |
| `get_property(property_name)` | Read one property definition |
| `upsert_property(property_name, schema, options)` | Create or update a typed property |
| `remove_property(property_name)` | Remove a property definition |
| `get_block_properties(block_uuid)` | Read all typed properties on a node |
| `get_block_property(block_uuid, property_name)` | Read one typed property |
| `upsert_block_property(block_uuid, property_name, value, options)` | Set a typed property |
| `remove_block_property(block_uuid, property_name)` | Remove a typed property |
| `get_tag(tag)` | Read a tag/class by name or UUID |
| `get_tag_objects(tag)` | Find nodes carrying a tag/class |
| `get_tags_by_name(tag_name)` | Find tags by name |
| `create_tag(tag_name, options)` | Create a tag/class |
| `add_block_tag(block_uuid, tag)` | Add a tag to a node |
| `remove_block_tag(block_uuid, tag)` | Remove a tag from a node |
| `add_tag_property(tag_id, value)` | Add a property to a tag/class |
| `remove_tag_property(tag_id, value)` | Remove a property from a tag/class |
| `add_tag_extends(tag_id, value)` | Add a parent class to a tag |
| `remove_tag_extends(tag_id, value)` | Remove a parent class from a tag |

All DB node mutations require UUID-based targets and are subject to the
namespace/tag access policy. Use `upsert_nodes` for related changes in one
request instead of issuing many individual writes.

### Typed DB properties

Prefer `get_block_properties`, `get_block_property`, `upsert_block_property`, and
`remove_block_property` for DB nodes. Use `upsert_block_property` with the
property's display name and a correctly typed value. `set_block_properties` is
the older compatibility handler and may not resolve newer typed property names;
use the typed handlers or `upsert_nodes` instead.

## DB calls that hang — do not use in DB mode

| Call | Why |
|---|---|
| `create_page` | Sends `{createFirstBlock: true}`, which hangs. |
| `Editor.getBlockProperties` / `removeBlockProperty` on a **page** UUID | Hang — no API route to un-recycle a page. |
| `update_page` | Page-targeted. |
| `get_page_content` | Page-targeted. |
| `get_page_backlinks` | Page-targeted; also unreliable historically. |
| `insert_nested_block` against a **page** UUID | Must target a block. |
| `get_block` with `include_children=false` | The argument itself hangs. |
| `rename_page`, `get_pages_from_namespace`, `get_pages_tree_from_namespace` | Fast HTTP 500 — file-graph concepts; DB pages no longer embed namespaces in names. |
| `find_pages_by_property` | Returns empty even for properties that exist. Use `query (property KEY)` instead. |

**If a call hangs, it may still have committed.** A timed-out `update_block` was confirmed
to have written its text. Always verify with `search` or `get_block` before retrying —
never assume success or failure.

## Workflows

### Correct or extend existing content

1. In DB mode, use `search_blocks` or `search` for a distinctive phrase; in file
  mode use `search`.
2. Use `get_block(uuid, include_children=true)` for a DB block subtree, or
  `get_page_content` for a file-graph page.
3. In DB mode, prefer one `upsert_nodes` batch for related edits. For a single
  DB block, use `update_block`, `upsert_block_property`, or the tag handlers.
  In file mode, use `update_block`, `insert_nested_block`, and `delete_block`.
4. `search` again to verify.

Draft the full set of edits before executing. Deciding mid-flight produces redundant calls
and corrections-to-corrections.

### Create a new page

`create_page` hangs, and a freshly created page has no block to anchor to. Two options:

**Have the user create the page in the UI** (fastest and safest), then `search` its title
to get a block UUID inside it and build downward with `insert_nested_block`.

**Or create it by curl**, which works with the right options:

```powershell
'{"method":"logseq.Editor.createPage","args":["My New Page",{},{"redirect":false}]}' | Set-Content -Path "$env:TEMP\q.json" -Encoding ascii -NoNewline
curl.exe -s -m 15 -w "`nHTTP %{http_code} in %{time_total}s`n" -X POST http://127.0.0.1:12315/api `
  -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" --data-binary "@$env:TEMP\q.json"
```

The page is created but empty, and inserting against its page UUID hangs — so it still
needs a first block added in the UI before MCP can fill it.

### Read a whole page without `get_page_content`

`search` a phrase from the page → take any hit's `page` UUID to confirm you have the right
page → `get_block(uuid, include_children=true)` on the top-level blocks to walk the tree.

For anything larger, query the graph directly by curl:

```powershell
'{"method":"logseq.DB.datascriptQuery","args":["[:find ?t :where [?b :block/uuid ?u] [?b :block/title ?t]]"]}' | Set-Content -Path "$env:TEMP\q.json" -Encoding ascii -NoNewline
curl.exe -s -m 15 -X POST http://127.0.0.1:12315/api -H "Authorization: Bearer YOUR_TOKEN" `
  -H "Content-Type: application/json" --data-binary "@$env:TEMP\q.json"
```

`DB.datascriptQuery` is fast and reaches the entire graph.

**DB schema names** (file-graph names will silently match nothing):

| Concept | DB attribute |
|---|---|
| Block text | `:block/title` (was `:block/content`) |
| Page name | `:block/title` (was `:block/original-name`) |
| Task status | `:logseq.property/status` (was `:block/marker`) |
| Priority | `:logseq.property/priority` |
| Deadline | `:logseq.property/deadline` |
| Ordering | `:block/order` (was `:block/left`) |
| Journal | `:blocks/tags :logseq.class/Journal` |
| Refs | `(has-ref ?b ?ref)` (was `:block/path-refs`) |

## Deletion — the most dangerous operation available

`delete_page` works and is fast. That makes it more dangerous, not less.

### `delete_page` and GUI deletion are NOT the same operation

Both soft-delete the page to the recycle bin — the entity survives, keeps its title and
UUID, and gains `:logseq.property/deleted-at`, `deleted-by-ref`, `recycle/original-page`.

They differ entirely in what happens to blocks that linked to the page:

| | Blocks linking to the deleted page |
|---|---|
| **GUI delete** | **Untouched.** Links still point at the recycled entity — they render as a gap or raw `[[uuid]]` while it sits in the bin, and **restoring repairs every one of them at once.** |
| **`delete_page` (MCP)** | **Destructively rewritten.** `[[Target]]` becomes bare text `Target` and the `refs` edge is dropped. **Restoring does NOT bring them back.** |

Both verified on the same graph: a page deleted through the GUI came back from the bin with
all inbound links live and `updatedAt` unchanged on the referencing blocks; a page deleted
with `delete_page` came back with every reference reduced to plain text.

This is the whole reason `delete_page` is dangerous. The success message —
*"permanently removed from LogSeq"* — is wrong twice over: it is neither permanent (soft
delete) nor clean (it rewrites other people's blocks).

**If a page must be deleted, the user should do it in the GUI.** Same recycle bin, no link
damage, and fully reversible.

### What Claude cannot do

| Operation | Available? |
|---|---|
| Delete a page | ✅ `delete_page` |
| Restore from the recycle bin | ❌ **GUI only** |
| Empty the recycle bin (true delete) | ❌ **GUI only** |
| Re-link blocks broken by a delete | ✅ but only by manual repair, block by block |

`Editor.getBlockProperties` and `removeBlockProperty` on a page UUID **hang** (HTTP 000), so
there is no API route to clear the recycle flags. The asymmetry is the point: **Claude can
delete but cannot undo.**

### `delete_page` targets by NAME, and cannot disambiguate

If two pages share a title — which happens easily, see the duplicate-page trap under
Workflows — `delete_page` resolves the name to **one** entity and there is no way to choose
which. Observed behaviour: it deleted the *real, content-bearing* page and left the empty
duplicate live.

**Never call `delete_page` on a title that is not unique.** Check first:

```
search(query="Page Title", format="json")
```

More than one entry in `pages` means the title is ambiguous → hand it to the user.

### Rules

**Default: Claude does not delete pages.** Deletion is the user's action, in the GUI, where
they can see what they are removing.

The single exception is a page **Claude created in the same session** and knows nothing links
to. Say so explicitly rather than assuming it.

**Before any deletion Claude must tell the user, in the same message:**

- which page, by title *and* UUID
- that it goes to the recycle bin, not away
- that **every inbound link will be broken and restoring will not fix them**
- how many inbound references exist (find them with `search`, never `get_page_backlinks`)
- that only they can restore it or empty the bin

Then wait for confirmation. Never delete a page in the same turn it was proposed.

**Never delete a page that anything links to.** To retire a page, repoint its references
first (see Repairing broken links), reduce the page to a one-line pointer, and let the user
delete it in the GUI.

### Auditing the recycle bin

Real content ends up in there and is easy to miss — a heavily-referenced page was found
sitting in the bin during testing. Check periodically, and always before the user empties it:

```powershell
'{"method":"logseq.DB.datascriptQuery","args":["[:find ?t ?u :where [?b :logseq.property/deleted-at _] [?b :block/title ?t] [?b :block/uuid ?u]]"]}' | Set-Content -Path "$env:TEMP\q.json" -Encoding ascii -NoNewline
curl.exe -s -m 20 -X POST http://127.0.0.1:12315/api -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" --data-binary "@$env:TEMP\q.json"
```

**Warn the user before they empty the bin.** Emptying is irreversible, and anything real in
there is lost for good.

## Finding accidental empty pages

Stray pages are easy to create by accident — a stray Enter in the search box, a `[[link]]`
typo, a property value entered once and abandoned, or a name-form `update_block` that spawned
a duplicate. They are invisible in normal use and quietly clutter search results and the
duplicate-title count.

An orphan is a page with **no content and nothing linking to it**. Those are safe to remove;
anything with either is not.

```powershell
'{"method":"logseq.DB.datascriptQuery","args":["[:find ?t ?u :where [?p :block/name] [?p :block/title ?t] [?p :block/uuid ?u] [?p :block/tags ?tag] [?tag :db/ident :logseq.class/Page] (not [?p :logseq.property/deleted-at _]) (not [_ :block/refs ?p]) (not [_ :block/parent ?p])]"]}' | Set-Content -Path "$env:TEMP\q.json" -Encoding ascii -NoNewline
curl.exe -s -m 30 -X POST http://127.0.0.1:12315/api -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" --data-binary "@$env:TEMP\q.json"
```

What each clause is doing, so it can be adjusted:

- `[?p :block/name]` — pages only, not blocks
- `:logseq.class/Page` — excludes property-definition and system pages (`category`, `status`,
  `Query`, `Asset`…), which are legitimately empty and must never be offered for deletion
- `(not [_ :block/refs ?p])` — nothing links to it
- `(not [_ :block/parent ?p])` — it has no blocks of its own
- `(not [?p :logseq.property/deleted-at _])` — already in the recycle bin

If the class filter returns nothing, drop the two `:block/tags` lines and filter the noise by
eye — system pages are recognisable by name.

### What to do with the results

**List them for the user; do not delete them.** Present title and UUID, note that each has no
content and no inbound links, and let them delete in the GUI. `delete_page` cannot be trusted
here: it resolves by name, and duplicate-title orphans are exactly the case where it deletes
the wrong one.

Cross-check anything surprising before listing it. A page can be empty and unlinked and still
be one the user is about to write. When in doubt, flag it rather than recommending removal.

Worth running after any bulk import or repair session, and alongside the duplicate-title check:

```
[:find ?t (count ?p) :where [?p :block/name] [?p :block/title ?t]]
```

Any title with a count above 1 is a duplicate — usually a name-form link that spawned a twin.

## Repairing broken links

Two different failures produce two different symptoms. Diagnose before repairing.

### Symptom A — plain text where a link should be

`The Slavemasters — overseers of the mines` with no brackets, while other links on the same
line render normally.

**Cause:** the target page was deleted; the delete rewrote this block.

**Repair:** confirm the target exists (restore it from the bin first if not), get its UUID
with `search`, and rewrite the block with a UUID link.

### Symptom B — a visible gap, and raw `[[uuid]]` when the block is opened

The rendered page shows a missing word; the raw text holds `[[6a84…]]` pointing at nothing.

**Cause:** the link was written when the target did not exist, so the UUID never resolved.

**Detection:** a ref is dangling when its UUID shares the **same 8-character prefix as the
block containing it** — both were minted in the same write batch. A healthy ref points at a
different page's UUID.

Enumerate every candidate:

```powershell
'{"method":"logseq.DB.datascriptQuery","args":["[:find ?u ?t :where [?b :block/uuid ?u] [?b :block/title ?t] [(clojure.string/includes? ?t \"[[6a\")]]"]}' | Set-Content -Path "$env:TEMP\q.json" -Encoding ascii -NoNewline
curl.exe -s -m 30 -X POST http://127.0.0.1:12315/api -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" --data-binary "@$env:TEMP\q.json"
```

Note that `search` **resolves valid refs to names and leaves dangling ones as raw UUIDs**, so
any `[[uuid]]` visible in `search` output is broken. Datascript shows raw storage, where
healthy refs are UUIDs too — do not mistake those for damage.

### Always link by UUID, never by name

`update_block` with `[[Page Name]]` is a **coin flip**. Logseq 2.0.1 sometimes matches the
existing page and sometimes creates a fresh empty duplicate carrying the same title. During
one rapid batch of edits, 8 of ~20 name-links created duplicates.

Writing `[[<target-page-uuid>]]` always binds to the intended page, and Logseq renders it as
the page name. This is also how the graph stores links internally.

```
1. search(query="Target Page") → take the uuid from the `pages` array
2. update_block(block_uuid=…, content="**Serves** [[6a846855-7d45-47ce-be30-73b89123b0cc]]")
3. get_block(uuid, include_children=true) → confirm `refs` gained an entry
```

**Verify by `refs`, not by text.** A block can display a name correctly while pointing at an
empty duplicate. Low entity ids are original pages; freshly created stubs have high ids.

### If duplicates were created

Find exactly what was created during the session:

```
[:find ?t ?u :where [?b :block/name] [?b :block/title ?t] [?b :block/uuid ?u]
                    [?b :block/created-at ?c] [(> ?c <session-start-ms>)]]
```

Repoint the affected blocks at the **real** UUID first, then leave the orphaned stubs for the
user to delete in the GUI — `delete_page` cannot target them by name.

### Recovering the original wording

The correct link target is often recoverable rather than guessable:

- the same fact stated elsewhere in the graph, with the link intact
- past conversations where the page was written — search them
- as a last resort, drop the link and leave readable prose

Never invent a referent. A confident wrong link is worse than an acknowledged gap. Where the
target is genuinely uncertain, list it for the user instead of choosing.

## Properties

**Property values written through the API are real and queryable, but they live in a plugin
namespace.** They are filed under `:plugin.property._test_plugin/KEY` rather than
`:user.property/KEY`, because Logseq sandboxes properties written by plugins and the HTTP
API identifies itself as one.

**`query (property KEY)` finds them normally** — verified: `species` exists only as
`:plugin.property._test_plugin/species`, and `query (property species)` returns all 11
pages. The DSL filter reaches the plugin namespace.

**`find_pages_by_property` does not** — it is the only tool with this blind spot. Use
`query` instead; an empty result from `find_pages_by_property` is never evidence of absence.

In a graph built through MCP, expect *every* property to be plugin-namespaced. Check with:

```
[:find ?a :where [?b :block/title "PAGE NAME"] [?b ?a ?v]]
```

### What works

| Call | Result |
|---|---|
| `upsert_block_property(block_uuid, property_name, value)` | ✅ Preferred MCP path for existing typed property values |
| `get_block_properties(block_uuid)` | ✅ Reads all typed values from a DB node |
| `get_block_property(block_uuid, property_name)` | ✅ Reads one typed value |
| `remove_block_property(block_uuid, property_name)` | ✅ Removes a typed value |
| `get_property(property_name)` | ✅ Reads a property definition |
| `upsert_property(property_name, schema, options)` | ✅ Creates or updates a typed property definition |
| `set_block_properties` | ⚠️ Compatibility handler; prefer the typed handlers above |

### Reading them

Query the explicit attribute with datascript:

```
[:find ?t :where [?b :plugin.property._test_plugin/status ?v] [?b :block/title ?t]]
```

This is the only reliable way to find MCP-written properties. It is fast (13ms across the
graph).

### Practical rule

Property **values** can be written with curl `upsertBlockProperty`. They are queryable via
`query (property KEY)` and **render normally in the Logseq UI** — verified on a page whose
properties are entirely plugin-namespaced. The namespace is internal bookkeeping and is not
visible to the user.

When creating a property where the type matters (Choice options, Node references, Date),
provide an explicit schema through `upsert_property` before bulk writes. Do not let the
first value accidentally determine the property type.

When a correction makes a property wrong and you cannot write it, report it:

```
Properties needing manual update on Kaz'gorrath:
  status: bound beneath the Tilean Sea  →  defeated ashore and banished
```

For **Claude-internal bookkeeping** that only Claude will read back, use a clearly named
property and the typed MCP handlers rather than issuing raw curl calls.

### Syntax that does not work

**`::` does nothing.** Properties in DB graphs are first-class entities, not parsed text.
Never emit `alias::`, `tags::`, `type::` — they render as literal characters. YAML
frontmatter is worse: it creates stray pages named after each key.

Built-ins (`alias`, `icon`, `tags`, `description`, `deadline`, `priority`) cannot be set
this way at all — a plugin-namespaced `alias` will not resolve names or merge backlinks.
Put alternate names in an `## Also known as` section and list them for manual entry.

Because property types are inferred from first use, **agree the field set before a bulk
import** and have the user create each property with a deliberate type (Text, Number, Date,
Checkbox, URL, Node, Choice) in the UI.

Avoid `&` in values intended to become hub pages — `Factions & Groups` does not produce a
page; `Factions and Groups` does.

## Behaviours worth knowing

- **Links auto-create pages.** Every `[[Target]]` creates a stub, so much of an import
  queue may already exist.
- **Property values auto-create pages.** `category: Characters` across 20 pages creates a
  `Characters` page.
- **References render as `[[uuid]]`** in raw output. That is normal DB output, not
  corruption — pages and blocks are both nodes, referenced the same way.
- **Page names are lowercased** in `list_pages` and lookups.
- **`updateBlock` returns `null` on success** at the HTTP level — a 200 with an empty body.
  Verify by reading back.

## What to tell the user up front

- Block-level work — creating, editing, deleting, restructuring — works well when paced;
  firing many writes back-to-back can wedge the server and force a restart.
- **Deleting a page breaks every link pointing at it, and restoring does not fix them.**
  Claude will not delete pages; that stays in the user's hands, in the GUI. Only the user can
  restore from the recycle bin or empty it.
- New pages need one manual step in the UI; after that Claude can fill them.
- Property values can be set and will display normally. Creating a *new* property is best
  done in the UI so its type is set deliberately.
- Corrections are made as targeted block edits. Restructuring gets asked about first.