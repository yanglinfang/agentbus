"""`abus` — the command-line face of the bus.

Identity comes from `--as NAME` or the ABUS_AGENT env var. There is no
per-checkout identity file on purpose: several agents share one checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .store import BROADCAST, Bus, BusError, Message, wait_for_new

def claude_hook(agent: str | None) -> dict:
    # Two modes. Fixed: `--as NAME` baked in (one Claude session per checkout).
    # Per-session (default): `hook-run` reads Claude's hook JSON from stdin and
    # derives `claude-<session_id[:6]>`, so two Claude sessions sharing a checkout
    # never collide. The injected header tells the session its own name.
    if agent:
        return {"hooks": {
            "UserPromptSubmit": [{"hooks": [{"type": "command",
                "command": f"abus --as {agent} inbox --format inject --ack --quiet-empty"}]}],
            "Stop": [{"hooks": [{"type": "command",
                "command": f"abus --as {agent} inbox --format inject --quiet-empty"}]}],
        }}
    return {"hooks": {
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "abus hook-run claude --ack"}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "abus hook-run claude"}]}],
    }}

INSTRUCTIONS = """\
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
"""


def _agent(args) -> str:
    name = getattr(args, "as_", None) or os.environ.get("ABUS_AGENT", "")
    if not name:
        raise BusError("who are you? pass --as NAME or set ABUS_AGENT")
    return name


def _bus(args) -> Bus:
    return Bus.open(Path(args.dir) if getattr(args, "dir", None) else None)


def _print_msgs(msgs: list[Message], fmt: str, bus: Bus, agent: str) -> None:
    if fmt == "json":
        print("\n".join(m.to_json() for m in msgs))
    elif fmt == "inject":
        sys.stdout.write(bus.render_inject(agent, msgs))
    else:
        for m in msgs:
            re = f" re {m.in_reply_to}" if m.in_reply_to else ""
            th = f" [{m.thread}]" if m.thread else ""
            print(f"{m.id:>6} {m.short_ts} {m.from_:>12} → {m.to:<8} {m.type:<9}{th}{re} {m.body}")
            if m.refs:
                print(f"{'':>6} {'':>11} refs: {', '.join(m.refs)}")


# ── commands ─────────────────────────────────────────────────────────────────
def cmd_init(args):
    root = Path(args.dir or ".").resolve()
    bus = Bus.init(root, args.name)
    print(f"initialised bus '{bus.name}' at {bus.path}")
    print("\nAdd this to CLAUDE.md / AGENTS.md / .cursorrules (or run `abus instructions`):\n")
    print(INSTRUCTIONS)


def cmd_instructions(args):
    print(INSTRUCTIONS)


def _maybe_wake(bus, args):
    if getattr(args, "wake", False) and args.to != BROADCAST:
        cmd = bus.wake_command(args.to)
        if cmd:
            ns = argparse.Namespace(dir=getattr(args, "dir", None), agent=args.to, dry_run=False, wait=False)
            cmd_wake(ns)
        else:
            print(f"(no wake registered for {args.to}; message queued)", file=sys.stderr)


def cmd_send(args):
    bus, me = _bus(args), _agent(args)
    m = bus.post(me, args.to, args.type, args.body, thread=args.thread or "",
                 refs=args.ref or [], confidence=args.conf or "", ack_required=args.ack_required)
    print(m.id); _maybe_wake(bus, args)


def cmd_claim(args):
    bus, me = _bus(args), _agent(args)
    m = bus.post(me, args.to, "claim", args.body, thread=args.thread or "",
                 refs=args.ref or [], confidence=args.conf or "medium")
    print(m.id)


def cmd_retract(args):
    bus, me = _bus(args), _agent(args)
    m = bus.post(me, BROADCAST, "retract", args.reason, in_reply_to=args.id)
    print(m.id)


def cmd_ask(args):
    bus, me = _bus(args), _agent(args)
    m = bus.post(me, args.to, "ask", args.body, thread=args.thread or "")
    print(m.id); _maybe_wake(bus, args)


def cmd_answer(args):
    bus, me = _bus(args), _agent(args)
    ask = bus.get(args.id)
    if ask is None or ask.type != "ask":
        raise BusError(f"{args.id} is not an ask")
    m = bus.post(me, ask.from_, "answer", args.body, thread=ask.thread,
                 refs=args.ref or [], in_reply_to=args.id)
    print(m.id)


def cmd_fact(args):
    bus = _bus(args)
    m = bus.post("user", BROADCAST, "user_fact", args.body, thread=args.thread or "",
                 refs=["user said"])
    print(m.id)


def cmd_status(args):
    bus, me = _bus(args), _agent(args)
    print(bus.post(me, BROADCAST, "status", args.body, ack_required=False).id)


def cmd_lock(args):
    bus, me = _bus(args), _agent(args)
    held = bus.locks().get(args.path)
    if held and held.from_ != me and not args.force:
        raise BusError(f"{args.path} is locked by {held.from_} since {held.short_ts} (use --force to override, and say why)")
    print(bus.post(me, BROADCAST, "lock", args.path, ack_required=False).id)


def cmd_unlock(args):
    bus, me = _bus(args), _agent(args)
    print(bus.post(me, BROADCAST, "unlock", args.path, ack_required=False).id)


def cmd_locks(args):
    for path, m in sorted(_bus(args).locks().items()):
        print(f"{path}  {m.from_}  since {m.short_ts}")


def cmd_inbox(args):
    bus, me = _bus(args), _agent(args)
    msgs = bus.inbox(me, include_broadcast=not args.direct_only)
    if not msgs:
        if not args.quiet_empty and args.format == "text":
            print(f"(inbox empty for {me})")  # machine formats stay silent
        return
    _print_msgs(msgs, args.format, bus, me)
    if args.ack:
        bus.ack(me, [m.id for m in msgs])


def cmd_ack(args):
    bus, me = _bus(args), _agent(args)
    bus.ack(me, args.ids)


def cmd_asks(args):
    bus = _bus(args)
    me = getattr(args, "as_", None) or os.environ.get("ABUS_AGENT", "")
    asks = bus.open_asks(for_agent=None if args.all else me or None)
    for m in asks:
        print(f"{m.id:>6} {m.short_ts} {m.from_} → {m.to}: {m.body}")
    if not asks:
        print("(no open asks)")


def cmd_log(args):
    bus = _bus(args)
    msgs = bus.thread(args.thread) if args.thread else list(bus.messages())
    if not args.acks:
        msgs = [m for m in msgs if m.type != "ack"]
    if args.n:
        msgs = msgs[-args.n:]
    _print_msgs(msgs, args.format, bus, "")


def cmd_head(args):
    print(_bus(args).render_head(), end="")


def cmd_watch(args):
    bus, me = _bus(args), _agent(args)
    print(f"watching bus '{bus.name}' as {me} (Ctrl-C to stop)")
    while True:
        msgs = wait_for_new(bus, me, poll=args.poll)
        sys.stdout.write("\a")
        sys.stdout.write(bus.render_inject(me, msgs))
        sys.stdout.flush()
        if args.exec:
            env = {**os.environ, "ABUS_AGENT": me, "ABUS_INJECT": bus.render_inject(me, msgs)}
            subprocess.call(args.exec, shell=True, env=env, cwd=bus.path.parent)
        if args.notify and shutil.which("osascript"):
            subprocess.run(["osascript", "-e",
                            f'display notification "{len(msgs)} new message(s)" with title "agentbus → {me}"'],
                           check=False)
        if args.ack:
            bus.ack(me, [m.id for m in msgs])
        else:
            return


def cmd_hook(args):
    if args.tool != "claude":
        raise BusError("only `abus hook claude` is implemented; for others see `abus instructions`")
    agent = getattr(args, "as_", None) or os.environ.get("ABUS_AGENT") or None
    spec = claude_hook(agent)
    if args.install:
        path = Path(args.dir or ".") / ".claude" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        current = json.loads(path.read_text()) if path.exists() else {}
        hooks = current.setdefault("hooks", {})
        for event, entries in spec["hooks"].items():
            # Replace any earlier abus hook for this event, then add ours.
            hooks[event] = [e for e in hooks.get(event, [])
                            if not any(h.get("command", "").startswith("abus ") for h in e.get("hooks", []))]
            hooks[event].extend(entries)
        path.write_text(json.dumps(current, indent=2) + "\n")
        mode = f"as {agent}" if agent else "per-session identity claude-<session_id>"
        print(f"installed Claude Code hooks ({mode}) into {path}")
    else:
        print(json.dumps(spec, indent=2))


def cmd_mcp(args):
    try:
        from .mcp_server import run
    except ImportError as e:
        raise BusError(f"MCP server needs the extra: pip install 'agent-bus[mcp]' ({e})")
    run(agent=_agent(args), start=Path(args.dir) if args.dir else None)


def cmd_hook_run(args):
    """Entry point for editor hooks. Reads the hook's JSON from stdin (Claude Code
    sends session_id, cwd, hook_event_name, ...) and shows the inbox for the
    per-session identity. Prints nothing when there is nothing new."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    bus = Bus.open(Path(payload.get("cwd")) if payload.get("cwd") else None)
    me = os.environ.get("ABUS_AGENT") or bus.session_name(str(payload.get("session_id", "")), args.tool)
    msgs = bus.inbox(me) if (bus.has_history(me) or bus.acked_by(me)) else bus.start_fresh(me)
    if not msgs:
        return
    sys.stdout.write(bus.render_inject(me, msgs))
    sys.stdout.write(f"(You are '{me}' on this bus. Use: abus --as {me} …)\n")
    if args.ack:
        bus.ack(me, [m.id for m in msgs])


def cmd_bind_session(args):
    """Pin an editor session (by session-id prefix) to an existing bus identity,
    so a hook-driven session keeps one name across restarts."""
    _bus(args).bind_session(args.session_prefix, args.name)
    print(f"sessions starting {args.session_prefix!r} will act as {args.name}")


def cmd_register_wake(args):
    bus = _bus(args)
    bus.register_wake(args.agent, args.command)
    print(f"wake for {args.agent}: {args.command}")


def cmd_wake(args):
    """Run an agent's registered wake command, as `<agent>-worker`. The worker
    can read the bus and act, and its posts are visibly its own — it never
    speaks as the live agent (see the incident that motivated this: a spawned
    codex worker posted as 'codex' while the real Codex session was active)."""
    bus = _bus(args)
    cmd = bus.wake_command(args.agent)
    if not cmd:
        raise BusError(f"no wake command registered for {args.agent}; use `abus register-wake {args.agent} '<cmd>'`")
    worker = f"{args.agent}-worker"
    env = {**os.environ, "ABUS_AGENT": worker, "ABUS_WAKE_TARGET": args.agent, "ABUS_BUS": str(bus.path.parent)}
    cmd = cmd.replace("{worker}", worker).replace("{agent}", args.agent).replace("{bus}", str(bus.path.parent))
    if args.dry_run:
        print(cmd); return
    bus.post("abus", BROADCAST, "note", f"waking {args.agent} as {worker}", ack_required=False)
    if args.wait:
        code = subprocess.call(cmd, shell=True, env=env, cwd=bus.path.parent)
        if code:
            raise BusError(f"wake command for {args.agent} exited {code}")
        return
    subprocess.Popen(cmd, shell=True, env=env, cwd=bus.path.parent, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"spawned wake for {args.agent} as {worker}")


def cmd_whoami(args):
    print(_agent(args))


# ── parser ───────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="abus", description="agentbus — coordinate coding agents through a file in the repo")
    p.add_argument("--as", dest="as_", metavar="NAME", help="your agent name (or set ABUS_AGENT)")
    p.add_argument("--dir", help="repo dir to look for .agentbus in (default: cwd upwards)")
    sp = p.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("init", help="create .agentbus in this repo"); s.add_argument("--name"); s.set_defaults(fn=cmd_init)
    sp.add_parser("instructions", help="print the block to paste into CLAUDE.md / AGENTS.md").set_defaults(fn=cmd_instructions)
    sp.add_parser("whoami").set_defaults(fn=cmd_whoami)

    s = sp.add_parser("send", help="send a note/status to an agent or *")
    s.add_argument("to"); s.add_argument("body"); s.add_argument("--type", default="note", choices=["note", "status"])
    s.add_argument("--thread"); s.add_argument("--ref", action="append"); s.add_argument("--conf")
    s.add_argument("--ack-required", action="store_true"); s.add_argument("--wake", action="store_true", help="run the recipient's registered wake command")
    s.set_defaults(fn=cmd_send)

    s = sp.add_parser("claim", help="state a fact; needs --ref")
    s.add_argument("body"); s.add_argument("--to", default=BROADCAST); s.add_argument("--ref", action="append", required=True)
    s.add_argument("--conf", choices=["low", "medium", "high"]); s.add_argument("--thread"); s.set_defaults(fn=cmd_claim)

    s = sp.add_parser("retract", help="withdraw a claim"); s.add_argument("id"); s.add_argument("--reason", required=True); s.set_defaults(fn=cmd_retract)

    s = sp.add_parser("ask", help="ask an agent (or *) a question that stays open until answered")
    s.add_argument("to"); s.add_argument("body"); s.add_argument("--thread"); s.add_argument("--wake", action="store_true"); s.set_defaults(fn=cmd_ask)
    s = sp.add_parser("answer", help="answer an ask by id"); s.add_argument("id"); s.add_argument("body"); s.add_argument("--ref", action="append"); s.set_defaults(fn=cmd_answer)
    s = sp.add_parser("asks", help="list open asks (for you, or --all)"); s.add_argument("--all", action="store_true"); s.set_defaults(fn=cmd_asks)

    s = sp.add_parser("fact", help="(human only) record something the user said, verbatim"); s.add_argument("body"); s.add_argument("--thread"); s.set_defaults(fn=cmd_fact)
    s = sp.add_parser("status", help="what you are doing / own right now"); s.add_argument("body"); s.set_defaults(fn=cmd_status)

    s = sp.add_parser("lock", help="claim a file path"); s.add_argument("path"); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_lock)
    s = sp.add_parser("unlock"); s.add_argument("path"); s.set_defaults(fn=cmd_unlock)
    sp.add_parser("locks").set_defaults(fn=cmd_locks)

    s = sp.add_parser("inbox", help="messages for you that you have not acked")
    s.add_argument("--ack", action="store_true", help="ack everything shown")
    s.add_argument("--format", default="text", choices=["text", "json", "inject"])
    s.add_argument("--direct-only", action="store_true"); s.add_argument("--quiet-empty", action="store_true")
    s.set_defaults(fn=cmd_inbox)
    s = sp.add_parser("ack"); s.add_argument("ids", nargs="+"); s.set_defaults(fn=cmd_ack)

    s = sp.add_parser("log", help="the full log (or one --thread)")
    s.add_argument("--thread"); s.add_argument("-n", type=int); s.add_argument("--acks", action="store_true")
    s.add_argument("--format", default="text", choices=["text", "json"]); s.set_defaults(fn=cmd_log)
    sp.add_parser("head", help="regenerate and print HEAD.md — current truth").set_defaults(fn=cmd_head)

    s = sp.add_parser("watch", help="block until something arrives; print it (and ring the bell)")
    s.add_argument("--poll", type=float, default=2.0); s.add_argument("--ack", action="store_true", help="keep watching, acking as you go")
    s.add_argument("--notify", action="store_true", help="macOS notification too")
    s.add_argument("--exec", metavar="CMD", help="run CMD for each batch (ABUS_INJECT holds the messages)"); s.set_defaults(fn=cmd_watch)

    s = sp.add_parser("hook", help="wake-up integration for a specific tool"); s.add_argument("tool", choices=["claude"])
    s.add_argument("--install", action="store_true"); s.set_defaults(fn=cmd_hook)
    s = sp.add_parser("hook-run", help="(called by editor hooks) show inbox for the per-session identity"); s.add_argument("tool", choices=["claude"]); s.add_argument("--ack", action="store_true"); s.set_defaults(fn=cmd_hook_run)
    s = sp.add_parser("bind-session", help="pin a hook session (id prefix) to an existing identity"); s.add_argument("session_prefix"); s.add_argument("name"); s.set_defaults(fn=cmd_bind_session)
    s = sp.add_parser("register-wake", help="store the shell command that wakes an agent (runs as <agent>-worker)"); s.add_argument("agent"); s.add_argument("command"); s.set_defaults(fn=cmd_register_wake)
    s = sp.add_parser("wake", help="run an agent's registered wake command as <agent>-worker"); s.add_argument("agent"); s.add_argument("--wait", action="store_true"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_wake)
    sp.add_parser("mcp", help="run the MCP stdio server (needs agent-bus[mcp])").set_defaults(fn=cmd_mcp)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
        return 0
    except BusError as e:
        print(f"abus: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
