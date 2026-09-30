"""MCP face of the bus — the same verbs as the CLI, as tools.

Run with:  abus --as <name> mcp
Configure in the agent (Claude Code, Cursor, Codex, …) as a stdio server:
  {"command": "abus", "args": ["--as", "claude", "mcp"]}
Each agent gets its own server process with its own identity.
"""

from __future__ import annotations

from pathlib import Path

from .store import BROADCAST, Bus, BusError


def run(agent: str, start: Path | None = None) -> None:
    # mcp 2.x renamed FastMCP -> MCPServer; the surface we use is identical.
    try:
        from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2
    except ImportError:  # pragma: no cover
        from mcp.server.fastmcp import FastMCP as Server  # mcp 1.x

    bus = Bus.open(start)
    mcp = Server("agentbus", instructions=(
        f"You are '{agent}' on bus '{bus.name}'. Other coding agents share this repo. "
        "Call inbox() at the start of a turn and before you finish. State facts with claim() "
        "and a source; correct yourself with retract(). Questions go through ask()/answer() and stay "
        "open until answered. lock() a path before editing something another agent may touch."))

    def _wrap(fn):
        try:
            return fn()
        except BusError as e:
            return f"error: {e}"

    @mcp.tool()
    def inbox(ack: bool = True) -> str:
        """Unread messages addressed to you (or to everyone). Acks them by default."""
        def go():
            msgs = bus.inbox(agent)
            text = bus.render_inject(agent, msgs) or "(inbox empty)"
            if ack and msgs:
                bus.ack(agent, [m.id for m in msgs])
            return text
        return _wrap(go)

    @mcp.tool()
    def send(to: str, body: str, thread: str = "") -> str:
        """Send a plain note to an agent name, or '*' for everyone."""
        return _wrap(lambda: bus.post(agent, to, "note", body, thread=thread).id)

    @mcp.tool()
    def status(body: str) -> str:
        """Say what you are working on / which files you own right now."""
        return _wrap(lambda: bus.post(agent, BROADCAST, "status", body, ack_required=False).id)

    @mcp.tool()
    def claim(body: str, refs: list[str], confidence: str = "medium", thread: str = "") -> str:
        """State a fact. refs = where the evidence is (file, log line, URL, 'user said'). Refused without refs."""
        return _wrap(lambda: bus.post(agent, BROADCAST, "claim", body, refs=refs, confidence=confidence, thread=thread).id)

    @mcp.tool()
    def retract(message_id: str, reason: str) -> str:
        """Withdraw one of your (or anyone's) earlier claims, with the reason."""
        return _wrap(lambda: bus.post(agent, BROADCAST, "retract", reason, in_reply_to=message_id).id)

    @mcp.tool()
    def ask(to: str, body: str, thread: str = "") -> str:
        """Ask an agent (or '*') a question. It stays listed as open until someone answers it."""
        return _wrap(lambda: bus.post(agent, to, "ask", body, thread=thread).id)

    @mcp.tool()
    def answer(ask_id: str, body: str, refs: list[str] | None = None) -> str:
        """Answer an open ask by id."""
        def go():
            a = bus.get(ask_id)
            if a is None or a.type != "ask":
                raise BusError(f"{ask_id} is not an ask")
            return bus.post(agent, a.from_, "answer", body, in_reply_to=ask_id, refs=refs or [], thread=a.thread).id
        return _wrap(go)

    @mcp.tool()
    def open_asks(all_agents: bool = False) -> str:
        """Questions nobody has answered yet — yours to answer unless all_agents=True."""
        def go():
            asks = bus.open_asks(for_agent=None if all_agents else agent)
            return "\n".join(f"{m.id} {m.from_} → {m.to}: {m.body}" for m in asks) or "(none)"
        return _wrap(go)

    @mcp.tool()
    def lock(path: str, force: bool = False) -> str:
        """Claim a file path before editing it. Fails if another agent holds it, unless force."""
        def go():
            held = bus.locks().get(path)
            if held and held.from_ != agent and not force:
                raise BusError(f"{path} is locked by {held.from_} since {held.short_ts}")
            return bus.post(agent, BROADCAST, "lock", path, ack_required=False).id
        return _wrap(go)

    @mcp.tool()
    def unlock(path: str) -> str:
        """Release a path you locked."""
        return _wrap(lambda: bus.post(agent, BROADCAST, "unlock", path, ack_required=False).id)

    @mcp.tool()
    def head() -> str:
        """Current truth: live facts, open asks, locks, agent statuses. Derived from the log."""
        return _wrap(bus.render_head)

    @mcp.tool()
    def log(thread: str = "", last: int = 30) -> str:
        """Recent messages (optionally one thread), acks hidden."""
        def go():
            msgs = bus.thread(thread) if thread else list(bus.messages())
            msgs = [m for m in msgs if m.type != "ack"][-last:]
            return "\n".join(f"{m.id} {m.short_ts} {m.from_}→{m.to} {m.type}: {m.body}" for m in msgs) or "(empty)"
        return _wrap(go)

    mcp.run()
