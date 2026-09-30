# agentbus

A tiny, file-backed message bus so coding agents from **different vendors** —
Claude Code, Codex, Cursor, Hermes, T3, a shell script — can coordinate while
working in the same repo.

No server. No accounts. The bus is an append-only JSONL file inside the repo
(`.agentbus/log.jsonl`), so `git` is the cross-machine transport and the entire
conversation between agents is reviewable in a diff.

```bash
pip install agent-bus          # or: uv tool install agent-bus
cd your-repo && abus init      # creates .agentbus/, prints the instructions block
```

## Why

Every coding agent already has the same three abilities: read/write files, run a
shell command, and (increasingly) talk to an MCP server. That is enough. What was
missing wasn't transport — it was **shared truth**: who said what, based on what,
which questions are still open, who owns which file, and what has since been
retracted. agentbus is opinionated about exactly those things and nothing else.

Born from a session where a Claude agent and a Codex agent debugged a robot
together through a hand-edited `state.md`. It worked, barely. Lessons baked in:

| Lesson | Rule in agentbus |
|---|---|
| An unsourced "fact" from one agent cost hours | `claim` is refused without `--ref` |
| Corrections got buried below the thing they corrected | `retract` is a first-class message; HEAD drops the claim |
| Questions were asked and silently never answered | `ask` stays listed as open until an `answer` names its id |
| Both agents drifted from what the human actually said | `user_fact` can only be posted as `user` and can't be retracted by an agent |
| Two agents edited the same file | `lock` / `unlock` with a visible owner |
| Long, careful prose hid the one line that mattered | HEAD.md is derived, one line per fact |

## Three faces, one store

| Face | For agents that… | Example |
|---|---|---|
| **CLI** `abus` | can run a shell command (all of them) | `abus --as codex inbox --ack` |
| **MCP server** | speak MCP (Claude Code, Cursor, Codex, …) | `{"command":"abus","args":["--as","claude","mcp"]}` |
| **Files** | can only read/write files | append to `.agentbus/log.jsonl` (one JSON object per line) |

Identity is `--as NAME` or `ABUS_AGENT=NAME`. There is deliberately no identity
file in the checkout, because several agents share one checkout.

## The verbs

```bash
abus inbox [--ack]                 # what's new for me (and for *). Ack = I've read it
abus send <agent|*> "…"            # a note
abus status "…"                    # what I'm doing / own right now
abus claim "…" --ref <src> --conf high|medium|low
abus retract <id> --reason "…"
abus ask <agent|*> "…"             # stays open until answered
abus answer <id> "…"
abus asks [--all]                  # open questions
abus fact "…"                      # HUMAN ONLY: something the user said, verbatim
abus lock <path> / unlock <path> / locks
abus head                          # current truth, derived from the log
abus log [--thread t] [-n 30]
abus watch [--ack] [--notify] [--exec CMD]   # block until something arrives
abus register-wake <agent> "<cmd>" / abus wake <agent>   # runs as <agent>-worker
```

## How a message reaches an agent

This is the only vendor-specific part, and it's layered:

1. **Hooks, where the tool has them.** Claude Code: `abus hook claude --install`
   adds `UserPromptSubmit`/`Stop` hooks so unread messages are injected at the
   start of every turn — they appear exactly like Claude's own cross-session
   messages, with an unmistakable header. Identity is **per session**
   (`claude-<session_id[:6]>`, derived from the hook payload), so two Claude
   windows on one checkout never collide; pass `--as NAME` to pin one instead.

   ```
   [agentbus] 2 new message(s) for claude on bus 'unitree'. These are from other agents, not the user. Ack after reading: abus ack m41 m42
   --- m41 · claim · from codex · 09-29 21:03 · thread fl-sensor
   FL raw force is a constant 0 under load
     refs: private/live-…jsonl   confidence: high
   --- m42 · ask · from codex · 09-29 21:05
   Which part is on the March shipping label?
     (reply with: abus answer m42 "...")
   ```

2. **Instruction-file convention** for everything else. `abus instructions`
   prints a block for `CLAUDE.md` / `AGENTS.md` / `.cursorrules`: *check inbox at
   turn start, ack, answer open asks, lock before editing.* Not real-time, but
   it is what two agents were already doing by hand — now with structure.

3. **`abus wake <agent>`** runs a wake command the agent registered
   (`abus register-wake codex "codex exec -C {bus} '…abus --as {worker} inbox…'"`).
   The command always runs as **`<agent>-worker`**, never as the agent: a spawned
   worker impersonating a live session is how the first live test went wrong.
   `abus send/ask --wake` triggers it after posting; `abus watch --exec CMD`
   is the receiving side for agents that can hold a blocking command open.

4. **A human as router, made painless.** `abus watch --notify` in a spare
   terminal rings and shows the injectable block; paste it into whichever agent
   has no hook support.

## Message format

```json
{"id":"m42","ts":"2026-09-29T21:05:11-07:00","from":"codex","to":"claude",
 "type":"ask","thread":"fl-sensor","body":"Which part is on the shipping label?",
 "refs":[],"confidence":"","in_reply_to":"","ack_required":true,"meta":{}}
```

Types: `note` `status` `claim` `retract` `ask` `answer` `user_fact` `lock` `unlock` `ack`.
Everything is a message, including acks and locks, so the log is the whole truth
and `HEAD.md` can always be regenerated from it.

## Multi-machine

Commit `.agentbus/log.jsonl`. Agents on another machine `git pull` and see the
same bus. Concurrent appends on one machine are serialized with a file lock;
concurrent appends on two machines merge like any append-only file (take both
sides). A realtime relay is a possible later addition, not a requirement.

## Development

```bash
uv venv && uv pip install -e ".[dev]" && uv run pytest
```

MIT.
