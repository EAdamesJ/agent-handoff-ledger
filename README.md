# Agent Handoff Ledger

**A shared, local task ledger for Claude Code, Codex, and DeepSeek Harness.** Agents leave a resumable brief, release the workspace to the next agent, and stop after a fixed handoff budget.

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-stdio-6C4)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Why this exists

Connecting two agents is the easy part. Keeping the task state, deciding who writes next, and preventing an endless back-and-forth is the harder part.

Agent Handoff Ledger gives every configured agent the same small local record:

- the goal and constraints;
- who currently owns the task;
- a handoff summary and next action;
- files changed so far;
- an append-only event history;
- a finite handoff budget.

The MCP server uses SQLite in the project directory. A transaction-backed workspace lease allows only one participating agent to hold the writer role at a time. The default lease lasts 90 minutes and can be renewed. A task defaults to four handoffs; when that budget runs out, the agent must stop and ask a person what to do.

## What it connects

The same local MCP server can be registered with:

- **Claude Code** using its local stdio MCP support;
- **Codex** using the local MCP server section in `config.toml`;
- **DeepSeek Harness** using its external MCP client plugin.

DeepSeek Harness is the MCP host in this setup. A DeepSeek API key is not needed by this ledger: it stores task state locally and does not call a model API.

## Install

Python 3.11+ and `uv` are required. Add the MCP server to each client you want to use. Replace the repository path with the absolute path to the project whose agents will share a ledger.

### Claude Code

Add this project-level server to `.mcp.json` at the project root:

```json
{
  "mcpServers": {
    "agent-handoff": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/EAdamesJ/agent-handoff-ledger.git",
        "agent-handoff"
      ],
      "env": {
        "AGENT_HANDOFF_ROOT": "/absolute/path/to/your/project"
      }
    }
  }
}
```

Claude Code documents project MCP servers in `.mcp.json` and launches local stdio servers as subprocesses. See [Claude Code MCP setup](https://code.claude.com/docs/en/mcp).

### Codex

Add this to `~/.codex/config.toml` or the trusted project's `.codex/config.toml`:

```toml
[mcp_servers.agent-handoff]
command = "uvx"
args = [
  "--from",
  "git+https://github.com/EAdamesJ/agent-handoff-ledger.git",
  "agent-handoff",
]

[mcp_servers.agent-handoff.env]
AGENT_HANDOFF_ROOT = "/absolute/path/to/your/project"
```

Codex's CLI, desktop app, and IDE extension use the same MCP configuration. See [Codex MCP configuration](https://developers.openai.com/codex/mcp).

### DeepSeek Harness

Add a local stdio entry to the profile's MCP client configuration. DeepSeek Harness documents external MCP servers through `@deepseek-ai/dsh-mcp-client`:

```yaml
- id: mcp-agent-handoff
  name: "@deepseek-ai/dsh-mcp-client"
  config:
    serverName: agent-handoff
    transport: stdio
    command: uvx
    args:
      - --from
      - git+https://github.com/EAdamesJ/agent-handoff-ledger.git
      - agent-handoff
    env:
      AGENT_HANDOFF_ROOT: !!js process.env.AGENT_HANDOFF_ROOT
```

Set `AGENT_HANDOFF_ROOT` in the environment that launches DeepSeek Harness. See the [DeepSeek Harness MCP client guide](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md).

If a client starts the server outside the project directory, set `AGENT_HANDOFF_ROOT` to the same absolute project path for every client. If the variable is unset, the server walks up from its working directory to the nearest `.git` directory or file.

## Use it

Each MCP tool returns JSON text. Ask the current agent to use the ledger before it starts a task, then hand the task to the next agent with a concrete summary and next action.

1. `create_handoff` records the objective and an optional target agent.
2. `claim_handoff` gives one agent the workspace writer lease.
3. The agent implements or reviews the task, then calls either:
   - `pass_handoff` to release the lease and queue the brief for another agent; or
   - `complete_handoff` to finish and release the lease.
4. The next agent calls `claim_handoff` before writing.
5. `show_handoff` returns the full brief and history; `list_handoffs` finds open work.
6. For long tasks, call `renew_handoff` before the lease expires.

Example handoff:

```text
create_handoff(
  title="Review the retry change",
  objective="Check the diff for correctness and edge cases. Do not edit files.",
  target_agent="claude-code"
)

claim_handoff(task_id="a1b2c3d4e5", agent="codex")
pass_handoff(
  task_id="a1b2c3d4e5",
  agent="codex",
  target_agent="claude-code",
  summary="The retry path handles 429, but the timeout branch can retry a non-idempotent request.",
  next_action="Inspect the timeout branch and decide whether to gate retries by method.",
  changed_files=""
)
```

The example IDs are illustrative. Use the ID returned by `create_handoff`.

## MCP tools

| Tool | Purpose |
| --- | --- |
| `create_handoff` | Create a persistent task brief with a target and handoff cap. |
| `claim_handoff` | Claim a queued task and the single writer lease for the project. |
| `renew_handoff` | Extend a lease held by the same agent. |
| `pass_handoff` | Save context, queue the task for another agent, and release the lease. |
| `complete_handoff` | Mark a task complete and release the lease. |
| `show_handoff` | Read the task and its history. |
| `list_handoffs` | List queued, active, or completed tasks. |

## State and safety

- State lives in `.agent-handoff/ledger.sqlite3`; the server creates a local `.gitignore` there so the ledger is not committed by default.
- Each project ledger allows one active writer lease. SQLite serializes concurrent claims.
- A stale lease expires after 90 minutes by default. On the next claim, its task returns to the queue with a warning to inspect the workspace.
- The handoff cap is four by default and can be set between 0 and 16 when a task is created.
- The server does not make network requests, call model APIs, launch agents, or execute shell commands.
- The lease is cooperative. It only coordinates agents that follow the MCP workflow; it cannot prevent a person or an unconfigured process from editing the same files.
- Task briefs and history are plain local data, not encrypted. Do not store credentials or secrets in them.

## Scope for v0.1

This first version focuses on a shared task ledger, one-writer coordination, resumable handoffs, and a finite loop budget. It does not invoke or sandbox Claude, Codex, or DeepSeek. Each client remains responsible for starting its own agent session and applying its own permissions.

## Market research

The idea and competitor scan behind this project are documented in [`docs/market-research.md`](docs/market-research.md). The short version: cross-agent interest is visible, direct provider setup is now documented by vendors, and a small but specific user pain remains around handoff state, writer conflicts, and runaway loops.

## Development

```sh
uv sync
uv run --with "mcp[cli]>=2.3.0,<3" mcp dev src/agent_handoff_ledger/server.py
```

The MCP Python SDK's `mcp dev` command opens the official Inspector against the local stdio server. See its [server running guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/index.md).

## License

MIT. See [LICENSE](LICENSE).