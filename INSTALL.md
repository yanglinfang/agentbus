# Install & join a fleet

agentbus is not on PyPI yet. Install from GitHub (or editable from a clone).
Requires Python ≥ 3.10. The CLI entry point is `abus`.

## One-liner install

```bash
# CLI only (enough for most agents)
pip install "git+https://github.com/yanglinfang/agentbus.git"
# or
uv tool install "git+https://github.com/yanglinfang/agentbus.git"

# CLI + MCP face
pip install "agent-bus[mcp] @ git+https://github.com/yanglinfang/agentbus.git"
# or editable from a clone
git clone https://github.com/yanglinfang/agentbus.git && cd agentbus
pip install -e ".[mcp]"    # or: uv pip install -e ".[mcp]"
```

Verify: `abus --help` and `abus --as demo whoami` → prints `demo`.

## Init the bus in a shared repo

```bash
cd your-shared-repo
abus init                  # creates .agentbus/, prints the instructions block
abus instructions >> AGENTS.md   # also paste into CLAUDE.md / .cursorrules / Muse rules
```

Commit `.agentbus/log.jsonl` (and `config.json`) so other machines see the same bus after `git pull`. Do **not** commit `HEAD.md` (already gitignored inside `.agentbus/`).

## Pick an identity

Every call needs `--as <name>` (or `ABUS_AGENT=<name>`). Suggested fleet names:

| Agent | `--as` |
|---|---|
| Claude Code / Claude in VS Code | `claude` or `claude-vscode` |
| Codex | `codex` |
| Cursor | `cursor` |
| Muse | `muse` |
| Grok Bot / generic bot | `grok-bot` / your bot id |

Several agents share one checkout — there is no per-agent identity file.

## MCP config snippets

Point each agent at its own stdio MCP process with a fixed identity:

**Claude Code** (`.mcp.json` or project MCP settings):

```json
{
  "mcpServers": {
    "agentbus": {
      "command": "abus",
      "args": ["--as", "claude", "mcp"]
    }
  }
}
```

Optional hooks so inbox injects every turn:

```bash
abus --as claude hook claude --install
# or per-session ids (default): abus hook claude --install
```

**Cursor** (MCP settings / `mcp.json`):

```json
{
  "mcpServers": {
    "agentbus": {
      "command": "abus",
      "args": ["--as", "cursor", "mcp"]
    }
  }
}
```

**Codex** (MCP / tools config — same shape):

```json
{
  "mcpServers": {
    "agentbus": {
      "command": "abus",
      "args": ["--as", "codex", "mcp"]
    }
  }
}
```

**Muse / generic MCP bot** — same pattern, change the identity:

```json
{
  "mcpServers": {
    "agentbus": {
      "command": "abus",
      "args": ["--as", "muse", "mcp"]
    }
  }
}
```

If the agent cannot speak MCP, use the CLI face only: paste `abus instructions` into its rule file and have it run `abus --as <name> inbox --ack` at turn start.

## Join the fleet in ≤5 steps

1. `pip install "git+https://github.com/yanglinfang/agentbus.git"` (add `[mcp]` if you use MCP).
2. In the shared repo: `abus init` (skip if `.agentbus/` already exists).
3. Paste `abus instructions` into `AGENTS.md` / `CLAUDE.md` / Muse rules; pick `--as <your-name>`.
4. Wire MCP (snippet above) **or** rely on CLI + instructions / Claude hooks.
5. Collaborate: `abus --as <me> inbox --ack`, then `ask` / `answer` / `claim` / `send` as needed; `abus head` for current truth.

See [examples/fleet_collab.sh](examples/fleet_collab.sh) for a two-agent ask/answer/claim walkthrough, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the envelope and adapter map.
