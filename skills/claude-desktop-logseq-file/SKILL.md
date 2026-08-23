---
name: claude-desktop-logseq-file
description: Detailed rules for safely reading, planning, and writing legacy Logseq Markdown/file graphs through mcp-logseq. Use Markdown pages, key:: value properties, page names, and targeted Editor-backed tools. Never use DB-node workflows.
---

# Logseq File Graphs over MCP

This skill applies only to a legacy Logseq Markdown/file graph. The MCP server
must run with `LOGSEQ_DB_MODE=false`. Do not use this skill with a Logseq 2.x
DB graph.

## Scope and configuration

This skill is deliberately file-graph-only. Use a dedicated MCP server with:

```json
{
  "LOGSEQ_DB_MODE": "false",
  "LOGSEQ_API_CONNECT_TIMEOUT": "10",
  "LOGSEQ_API_READ_TIMEOUT": "60",
  "PYTHONIOENCODING": "utf-8"
}
```

Do not use `LOGSEQ_DB_MODE=auto` with this skill. Do not load the DB-graph
skill in the same Claude conversation.

## File-graph data model

- Pages are Markdown files and are addressed by page name.
- Properties use `key:: value` syntax and Markdown-compatible values.
- Nested blocks form the page's Markdown outline.
- Slash-separated page names represent namespaces.

Do not import DB-graph assumptions into a file graph:

- No `upsert_nodes`, DB node batching, typed property schemas, or tag/class
  modeling.
- No `get_page_data`, `search_blocks`, or DB UUID-relationship workflows.
- Do not treat `block/title`, `block/uuid`, or property entities as the
  canonical file-graph representation.

## File structure and query schema

### Pages and blocks

- A page is Markdown content addressed by its exact page name.
- Indented Markdown list items represent parent and child blocks.
- Block UUIDs identify existing blocks for targeted edits, but page names and
  Markdown remain the canonical representation of the graph.
- `[[Page Name]]` creates a page reference. Search before adding a reference
  when a similarly named page may already exist.
- A slash in `parent/child` is a file-graph namespace convention. It is not a
  DB parent relationship.

### Properties

- Use `key:: value` on a property line. Consecutive property lines at the top
  of a page are page properties; property lines inside a block belong to that
  block.
- Preserve an existing YAML frontmatter convention when a page uses it. Do not
  casually mix frontmatter and inline properties on the same page.
- Use scalar Markdown-compatible values unless the page already establishes a
  list or reference convention.
- File-graph properties are queried by their textual key and value. They are
  not typed property entities and do not use `logseq.property/*` fields.

### Query vocabulary

Use the file-graph DSL forms:

| Need | File-graph query form |
| --- | --- |
| Pages with a property | `(page-property status active)` |
| Pages carrying a tag | `(page-tags [[Project]])` |
| Task blocks | `(task todo)` |
| Priority | `(priority A)` |
| Combine conditions | `(and (task todo) (page [[Project]]))` |

Do not use DB-only query vocabulary in a file graph: `(property key)`,
`(tags tag)`, `:block/title`, `:logseq.property/status`, or
`:logseq.property/priority`.

## Operational stance

Preserve the page's existing structure and voice. Correct the smallest block
or property that solves the problem. A change that requires reorganizing a
page, changing its template, or resolving an ambiguous source needs a user
decision before mutation.

## Build the change plan in memory first

Do discovery and reasoning before making the first edit. Build a structured
plan in the conversation rather than testing ideas by partially changing the
graph.

For every planned edit, record:

```text
target page: exact page name and relevant namespace
target block: UUID, current content, parent/sibling context
intent: create | append | replace | edit block | remove block | set property
replacement: exact final Markdown or property value
evidence: source fact or user instruction
dependencies: required page links, block UUIDs, and page/property checks
verification: page read or search after commit
```

Before deployment, check the plan for:

1. Contradictory replacements to the same block or page.
2. A correction that answers an open question but leaves stale text behind.
3. Headings, summaries, or links that become inaccurate after the edit.
4. Broken `[[Page Name]]` links, accidental duplicate page names, or namespace
   mistakes.
5. Property values that need normalizing before writing.

Draft all final Markdown before making the first change. Preserve indentation,
list style, headings, and templates unless the user explicitly requests a
restructure.

## Read workflow

1. Use `search` to find pages and blocks, then capture exact page names and
   block UUIDs.
2. Use `get_page_content` to read a complete page and its Markdown block tree.
3. Normalize relevant content in memory: page properties, block UUIDs, current
   text, parent/child relationships, and incoming/outgoing page references.
4. Use `get_block` for a known block UUID when only one outline branch needs
   inspection.
5. Use `query` and `find_pages_by_property` for file-graph queries.
6. Use `get_pages_from_namespace` and `get_pages_tree_from_namespace` for
   namespace navigation.

## Write workflow

- Use `create_page` with complete initial Markdown only after checking that the
  target page does not already exist.
- Use `update_page` in `append` mode for genuinely additive material.
- Use `update_page` in `replace` mode only after the user explicitly approved a
  complete page replacement and the replacement text is fully drafted.
- Use `update_block`, `delete_block`, and `insert_nested_block` for local,
  minimal-diff outline edits.
- Use page/block property handlers for Markdown-backed properties.

Apply changes in dependency order: create required target pages first, then
insert or update blocks that link to them, then set properties that describe the
finished content. Verify each significant edit with `get_page_content` or
`search` before performing a dependent destructive action.

## Markdown property and namespace rules

- Use `key:: value` only for file-graph page or block properties.
- Preserve existing property capitalization and value style unless the user
  requests normalization.
- Use exact page names in `[[Page Name]]` links. Search first when a target may
  already exist; do not create near-duplicate pages by guessing casing or a
  namespace.
- Treat `project/plan` as a namespace relationship. Check the namespace tree
  before moving or renaming pages.
- Use `rename_page` only after reviewing inbound links and same-name conflicts.

## Minimal-diff editing rules

- Change one block when one statement is wrong.
- Add a child or sibling only when the intended parent and order are known.
- Delete a block only when its subtree is intentionally obsolete.
- Do not replace a full page to correct a sentence.
- If an edit resolves an obsolete question, placeholder, or contradiction,
  remove or replace the stale material in the same plan.
- Preserve voice and template; raise editorial judgment calls instead of making
  unrequested structural changes.

Verify significant edits with `get_page_content` or `search`.

## Text formatting rules

- Use ASCII punctuation in generated Logseq content.
- Do not use em dashes. Use a period, comma, colon, parentheses, or a new
  sentence instead.
- Preserve the page's existing heading, list, indentation, and emphasis style.
- Keep blocks concise and give each block one clear idea.
- Use Markdown links and emphasis only when they match the surrounding page.
- Use `key:: value` only for an intentional file-graph property, never as
  decorative prose.

## File-safe tool choices

| Need | Use |
|---|---|
| Find content | `search` |
| Read a page/tree | `get_page_content` |
| Read a block | `get_block` |
| Create a page | `create_page` |
| Modify a page | `update_page` |
| Modify outline blocks | `update_block`, `insert_nested_block`, `delete_block` |
| Query properties | `query`, `find_pages_by_property` |
| Browse namespaces | `get_pages_from_namespace`, `get_pages_tree_from_namespace` |

Do not use DB-only tools or assumptions: `get_page_data`, `search_blocks`,
`list_tags`, `list_properties`, `upsert_nodes`, typed DB properties, DB UUID
relationship operations, or DB class/tag modeling.

## Failure handling and recovery

- A timeout does not establish whether a write committed. Read the target page
  or search for the exact changed text before retrying.
- If a page update times out, do not repeat a `replace` operation from stale
  content. First fetch the current page, compare it to the in-memory plan, and
  construct only the remaining edits.
- If Logseq's API server was restarted, start a new Claude conversation so the
  MCP session has fresh connections.
- On Windows, retain `PYTHONIOENCODING=utf-8` so non-ASCII Logseq content and
  logging do not break diagnostics.

## Response discipline

Before a broad, destructive, or ambiguous change, show the user:

- the page and block UUIDs affected;
- the exact proposed Markdown or property values;
- any links, namespaces, or properties that will change;
- any source conflict or editorial uncertainty; and
- the planned verification read.

Do not claim an edit succeeded based only on the write response. Claim success
after the verification read shows the planned file-graph state.