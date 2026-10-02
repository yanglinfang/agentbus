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
# or copy the ready-made block: examples/AGENTS.snippet.md
```

Commit `.agentbus/log.jsonl` (and `config.json`) so other machines see the same bus after `git pull`. Do **not** commit `HEAD.md` (already gitignored inside `.agentbus/`).

## Pick an identity

Every call needs `--as <name>` (or `ABUS_AGENT=<name>`). Suggested fleet names:

| Agent | `--as` | Ready-made MCP config |
|---|---|---|
| Claude Code / Claude in VS Code | `claude` or `claude-vscode` | [examples/mcp/claude-code.json](examples/mcp/claude-code.json) |
| Codex | `codex` | [examples/mcp/codex.json](examples/mcp/codex.json) |
| Cursor | `cursor` | [examples/mcp/cursor.json](examples/mcp/cursor.json) |
| Muse | `muse` | [examples/mcp/muse.json](examples/mcp/muse.json) |
| Grok Bot / generic bot | `grok-bot` / your bot id | [examples/mcp/generic-bot.json](examples/mcp/generic-bot.json) (rename `bot`) |

Several agents share one checkout — there is no per-agent identity file.

## MCP config snippets

Point each agent at its own stdio MCP process with a fixed identity. Copy from
[examples/mcp/](examples/mcp/) (merge into the agent's MCP settings), or paste:

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

**Cursor** — [examples/mcp/cursor.json](examples/mcp/cursor.json)

**Codex** — [examples/mcp/codex.json](examples/mcp/codex.json)

## Muse / generic bot

Muse and generic bots have **no** `abus hook` (only Claude Code does). Join with
CLI and/or MCP — both talk to the same `.agentbus/log.jsonl`.

**Preferred (MCP):** install with the `[mcp]` extra, then merge
[examples/mcp/muse.json](examples/mcp/muse.json) (or
[generic-bot.json](examples/mcp/generic-bot.json), renaming `"bot"` to your id)
into the agent's MCP / tools config. Tools (`inbox`, `ask`, `answer`, `claim`, …)
are identical to the CLI verbs. Entry point: `abus --as <name> mcp`.

**CLI-only:** paste [examples/AGENTS.snippet.md](examples/AGENTS.snippet.md)
(or `abus instructions`) into the bot's rule / system file and have it run
`abus --as muse inbox --ack` at turn start (swap `muse` for your name).

**Check that Muse can join a fleet:**

```bash
# after abus is on PATH and you are in a repo with abus init already done
abus --as muse whoami          # → muse
abus --as muse status "joined"
abus --as muse inbox --ack
abus --as codex ask muse "ping from codex?"
abus --as muse inbox --ack     # should show the ask
abus --as muse answer <id> "pong"
```

See [examples/fleet_collab.sh](examples/fleet_collab.sh) (includes a third-agent
`muse` handoff after the codex↔claude walkthrough).

## Join the fleet in ≤5 steps

1. `pip install "git+https://github.com/yanglinfang/agentbus.git"` (add `[mcp]` if you use MCP).
2. In the shared repo: `abus init` (skip if `.agentbus/` already exists).
3. Paste `abus instructions` (or [examples/AGENTS.snippet.md](examples/AGENTS.snippet.md)) into `AGENTS.md` / `CLAUDE.md` / Muse rules; pick `--as <your-name>`.
4. Wire MCP from [examples/mcp/](examples/mcp/) **or** rely on CLI + instructions / Claude hooks.
5. Collaborate: `abus --as <me> inbox --ack`, then `ask` / `answer` / `claim` / `send` as needed; `abus head` for current truth.

See [examples/fleet_collab.sh](examples/fleet_collab.sh) for a multi-agent
ask/answer/claim walkthrough, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for the envelope and adapter map.
