# Paste into AGENTS.md / CLAUDE.md / .cursorrules / Muse rules

Replace `<me>` below with your fleet identity (`claude`, `codex`, `cursor`, `muse`, `bot`, …).
Regenerate anytime with: `abus instructions`

For MCP wiring, copy the matching file from [mcp/](mcp/).

## Agent coordination (agentbus)

Other coding agents work in this repo. Coordinate through the bus, not by
editing each other's files. Pass your identity on EVERY call as
`abus --as <your-name> …` — do not rely on an exported ABUS_AGENT, because many
agent shells do not persist environment between commands.

- Start of every turn: `abus --as <me> inbox --ack`. Before you finish: `abus --as <me> inbox`.
- State a fact:  `abus --as <me> claim "…" --ref <file-or-url> --conf high|medium|low`
  A claim without a source is refused. Correct yourself with `abus --as <me> retract <id> --reason "…"`.
- Ask / answer:  `abus --as <me> ask <agent|*> "…"`  →  `abus --as <me> answer <id> "…"`.
  Open asks are listed by `abus head`; answer them or say why you can't.
- Before editing a file another agent may touch: `abus --as <me> lock <path>`; `unlock` when done.
- `abus --as <me> status "…"` says what you own right now. `abus head` shows current truth.
- Delivery: messages are seen when an agent checks — at its turn boundaries (hook or
  habit) or while it runs `abus --as <me> watch`. Posting does NOT wake an idle agent;
  if you need a human to nudge one, say so in your message.
- Never edit `.agentbus/log.jsonl` or `HEAD.md` by hand. Never post as `user`.

