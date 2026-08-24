# Installation and Deployment

This guide covers installing the current `mcp-logseq` checkout and connecting it
to Claude Code or Claude Desktop.

> [!WARNING]
> This MCP can create, edit, move, and delete Logseq pages, blocks, tags,
> properties, and files. Back up your graph, review planned changes, and grant
> destructive access deliberately. Client confirmation prompts are not
> guaranteed by the MCP.

## Prerequisites

- Logseq 2.x with its HTTP API server enabled and started.
- A Logseq API token.
- Python 3.11 or newer.
- `uv`, the Python package and environment manager.
- Claude Code or Claude Desktop.

Use one graph mode per MCP server:

- `LOGSEQ_DB_MODE=true` for a Logseq 2.x DB graph.
- `LOGSEQ_DB_MODE=false` for a legacy Markdown/file graph.

Do not load both graph skills in the same Claude conversation.

## What the uv Commands Mean

`uv` creates isolated Python environments, installs the project dependencies,
and runs the project's console entry point without requiring a global Python
installation.

```text
uv sync --extra vector
```

Run this from the repository directory. It creates or updates `.venv` and
installs this checkout plus the optional vector dependencies.

```text
uv run --project "<REPO_DIR>" mcp-logseq
```

Run the `mcp-logseq` command from a specific local checkout. This is useful for
Claude Code and development because it runs the code you cloned, not a package
selected from a registry.

```text
uvx --from "mcp-logseq @ git+https://github.com/LoveSkylark/mcp-logseq.git" mcp-logseq
```

Download the package from GitHub into a temporary isolated environment and run
it. This is convenient for a remote deployment, but it depends on GitHub and
`uv`'s package cache. A local checkout is more deterministic when debugging.

To use a particular Git branch:

```text
uvx --from "mcp-logseq @ git+https://github.com/LoveSkylark/mcp-logseq.git@main" mcp-logseq
```

`--with` adds a dependency to an existing `uv run` environment. It is useful
for dependencies such as `mcp>=2,<3`, but `--project` is preferred here because
this repository already declares its dependencies and console entry point.

## Enable the Logseq API

1. In Logseq, open `Settings > Features` and enable the HTTP API server.
2. Open the API panel and start the server.
3. Create or copy an authorization token.
4. Confirm the API endpoint is reachable at `http://127.0.0.1:12315/api`.

## Install the Local Checkout

Clone this repository wherever you keep source code, then substitute that path
for `<REPO_DIR>` in the commands below.

```powershell
Set-Location "<REPO_DIR>"
uv sync --extra vector
```

The installed console executable is:

```text
Windows:   <REPO_DIR>\\.venv\\Scripts\\mcp-logseq.exe
macOS/Linux: <REPO_DIR>/.venv/bin/mcp-logseq
```

Launching this executable directly avoids stale PyPI packages, Git branch
resolution, and unrelated `uv` cache entries.

## Claude Desktop: Local Checkout

Edit Claude Desktop's configuration file and use the executable created above.
Replace `<REPO_DIR>` with the real path. On Windows, use doubled backslashes in
JSON paths.

```json
{
  "mcpServers": {
    "logseq-db": {
      "command": "<REPO_DIR>\\.venv\\Scripts\\mcp-logseq.exe",
      "args": [],
      "env": {
        "LOGSEQ_API_TOKEN": "your-logseq-api-token",
        "LOGSEQ_API_URL": "http://127.0.0.1:12315",
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

For a legacy file graph, change the server name and set:

```json
"LOGSEQ_DB_MODE": "false"
```

Fully quit Claude Desktop before changing the configuration, then relaunch it
and start a new conversation.

## Claude Code: Local Checkout

Claude Code must be installed separately and available as the `claude` command.
From any terminal:

```bash
claude mcp add logseq-db \
  --env LOGSEQ_API_TOKEN=your-logseq-api-token \
  --env LOGSEQ_API_URL=http://127.0.0.1:12315 \
  --env LOGSEQ_DB_MODE=true \
  --env LOGSEQ_API_CONNECT_TIMEOUT=10 \
  --env LOGSEQ_API_READ_TIMEOUT=60 \
  --env MCP_READ_TOOL_TIMEOUT=90 \
  --env MCP_MAX_RESPONSE_CHARS=30000 \
  --env PYTHONIOENCODING=utf-8 \
  -- uv run --project "<REPO_DIR>" mcp-logseq
```

On Windows PowerShell, the same command can be entered on one line if shell
continuation characters are inconvenient.

## Claude Desktop: GitHub Package

This option does not require a local checkout. It downloads the package from
GitHub when the server is started:

```json
{
  "mcpServers": {
    "logseq-db": {
      "command": "uvx",
      "args": [
        "--from",
        "mcp-logseq @ git+https://github.com/LoveSkylark/mcp-logseq.git@main",
        "mcp-logseq"
      ],
      "env": {
        "LOGSEQ_API_TOKEN": "your-logseq-api-token",
        "LOGSEQ_API_URL": "http://127.0.0.1:12315",
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

Use a commit SHA instead of `main` when reproducibility matters. After a new
commit, run `uv cache clean` or use a fresh SHA if the client appears to run old
code. The local-checkout method is preferred for development and diagnosis.

## Claude Code: GitHub Package

```bash
claude mcp add logseq-db \
  --env LOGSEQ_API_TOKEN=your-logseq-api-token \
  --env LOGSEQ_API_URL=http://127.0.0.1:12315 \
  --env LOGSEQ_DB_MODE=true \
  --env LOGSEQ_API_CONNECT_TIMEOUT=10 \
  --env LOGSEQ_API_READ_TIMEOUT=60 \
  --env MCP_READ_TOOL_TIMEOUT=90 \
  --env MCP_MAX_RESPONSE_CHARS=30000 \
  --env PYTHONIOENCODING=utf-8 \
  -- uvx --from "mcp-logseq @ git+https://github.com/LoveSkylark/mcp-logseq.git@main" mcp-logseq
```

## Verify the Deployment

After restarting the client, confirm that the expected tools are present. In DB
mode, use `get_page_data`, `get_block`, and `search_blocks`. Raw
`datascriptQuery` is an internal implementation detail and is not an MCP tool.

If the client shows an old schema or old behavior:

1. Fully quit the client and terminate stale MCP processes.
2. Confirm the configuration points to one server only.
3. Prefer the local executable from `<REPO_DIR>/.venv`.
4. If using GitHub, pin a fresh commit SHA or clear the `uv` cache.
5. Start a new client conversation.

## Updating a Local Installation

```powershell
Set-Location "<REPO_DIR>"
git pull --ff-only origin main
uv sync --extra vector
```

Restart the MCP client after updating. The MCP process loads code at startup.

## ChatGPT: Remote MCP Connection

ChatGPT connects to remote MCP servers. It does not launch a local stdio
executable such as `.venv/Scripts/mcp-logseq.exe` directly. To connect this
project to ChatGPT, run `mcp-logseq` with HTTP transport and provide ChatGPT
with a reachable HTTPS MCP endpoint.

Start the server from the local checkout:

```powershell
Set-Location "<REPO_DIR>"
uv sync --extra vector
$env:LOGSEQ_DB_MODE = "true"
$env:LOGSEQ_API_TOKEN = "your-logseq-api-token"
$env:MCP_HTTP_AUTH_TOKEN = "your-mcp-http-token"
& ".\.venv\Scripts\mcp-logseq.exe" --transport http --host 127.0.0.1 --port 12320
```

The MCP endpoint is:

```text
http://127.0.0.1:12320/mcp
```

Do not expose that plain HTTP address to the public internet. For ChatGPT,
place the server behind an HTTPS reverse proxy or use an OpenAI-supported
[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
so the endpoint is reachable without exposing the local machine directly.
The remote endpoint must preserve the `/mcp` path and forward the bearer
authorization header.

In ChatGPT web, enable Developer mode or custom MCP apps if your plan and
workspace allow it, create a custom app/connector, enter the HTTPS MCP
endpoint, select the supported authentication mechanism, scan the tools, and
test the draft app. Review the requested actions before publishing. ChatGPT
may ask for confirmation for write actions, but app permissions and workspace
policy determine which actions are available.

Full MCP write support is currently available in beta for ChatGPT Business,
Enterprise, and Edu workspaces. Other plans may provide only read/fetch access.
ChatGPT custom apps are web-only, and workspace admins may need to enable
Developer mode and approve or refresh the app's actions after server changes.

For a read-only ChatGPT connection, add `--read-only` to the server command.
This removes Logseq write tools from the exposed MCP server:

```powershell
& ".\.venv\Scripts\mcp-logseq.exe" --transport http --host 127.0.0.1 --port 12320 --read-only
```

For a DB graph, also set `LOGSEQ_DB_MODE=true`; for a legacy file graph, use
`LOGSEQ_DB_MODE=false`. Keep `MCP_HTTP_AUTH_TOKEN` separate from the Logseq
API token. The first authenticates the remote MCP client, while the second
authenticates this server to Logseq.
