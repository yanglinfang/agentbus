# MCP configs (copy into your agent)

Each file is a drop-in `mcpServers` fragment for `abus --as <name> mcp`.
Install the package first (`pip install "agent-bus[mcp] @ git+https://github.com/yanglinfang/agentbus.git"`), then merge the matching JSON into the agent's MCP settings.

| File | Identity (`--as`) | Typical host |
|---|---|---|
| [claude-code.json](claude-code.json) | `claude` | Claude Code / Claude in VS Code |
| [codex.json](codex.json) | `codex` | OpenAI Codex |
| [cursor.json](cursor.json) | `cursor` | Cursor |
| [muse.json](muse.json) | `muse` | Muse |
| [generic-bot.json](generic-bot.json) | `bot` | Any MCP bot — rename `bot` to your id |

Muse and generic bots have **no** `abus hook` (only Claude Code does). Use MCP tools and/or paste [../AGENTS.snippet.md](../AGENTS.snippet.md) into the bot's rule file so it runs `inbox --ack` every turn.

Replace `"command": "abus"` with an absolute path if `abus` is not on the agent's PATH (e.g. `"/home/you/.local/bin/abus"` or your venv's `bin/abus`).
