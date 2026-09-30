"""The store: one append-only JSONL log per bus, plus derived views.

Design rules, each learned the hard way from two agents sharing a repo:

* Append-only. Nothing is edited or deleted; corrections are `retract` messages.
* Every claim carries `refs` (where the evidence is). A claim without a source
  is refused — an unsourced "fact" from one agent became hours of wasted work.
* Asks have ids and stay open until an `answer` names them, so nothing is lost.
* A `user_fact` is authored only by the human and is never superseded by an agent.
* HEAD (current truth) is *derived* from the log, never hand-edited.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

BUS_DIR = ".agentbus"
LOG = "log.jsonl"
CONFIG = "config.json"
HEAD = "HEAD.md"
BROADCAST = "*"

TYPES = {
    "note",        # plain message
    "status",      # what I'm doing / owning right now
    "claim",       # a fact, with refs and confidence
    "retract",     # withdraw an earlier claim (in_reply_to = its id)
    "ask",         # a question that stays open until answered
    "answer",      # answers an ask (in_reply_to = ask id)
    "user_fact",   # verbatim from the human; agents cannot author or supersede
    "lock",        # I own this path until unlock
    "unlock",
    "ack",         # I have seen message X (in_reply_to = X)
}
CONFIDENCE = {"low", "medium", "high"}


class BusError(Exception):
    pass


@dataclass
class Message:
    id: str
    ts: str
    from_: str
    to: str
    type: str
    body: str
    thread: str = ""
    refs: list[str] = field(default_factory=list)
    confidence: str = ""
    in_reply_to: str = ""
    ack_required: bool = False
    meta: dict = field(default_factory=dict)

    def to_json(self) -> str:
        d = asdict(self)
        d["from"] = d.pop("from_")
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "Message":
        d = json.loads(line)
        d["from_"] = d.pop("from")
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @property
    def short_ts(self) -> str:
        try:
            return datetime.fromisoformat(self.ts).strftime("%m-%d %H:%M")
        except ValueError:
            return self.ts


def find_bus(start: Path | None = None) -> Path | None:
    """Walk up from `start` looking for a .agentbus directory, like git does."""
    p = Path(start).resolve() if start else Path.cwd().resolve()
    for d in [p, *p.parents]:
        if (d / BUS_DIR).is_dir():
            return d / BUS_DIR
    return None


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Bus:
    def __init__(self, path: Path):
        self.path = path
        self.log_path = path / LOG
        self.config_path = path / CONFIG

    # ── lifecycle ────────────────────────────────────────────────────────────
    @classmethod
    def init(cls, root: Path, name: str | None = None) -> "Bus":
        path = root / BUS_DIR
        path.mkdir(parents=True, exist_ok=True)
        bus = cls(path)
        if not bus.config_path.exists():
            bus.config_path.write_text(json.dumps({
                "name": name or root.resolve().name,
                "created": now_iso(),
                "version": 1,
            }, indent=2) + "\n")
        bus.log_path.touch()
        bus.render_head()
        return bus

    @classmethod
    def open(cls, start: Path | None = None) -> "Bus":
        path = find_bus(start)
        if path is None:
            raise BusError("no .agentbus here or above — run `abus init` in the repo root")
        return cls(path)

    @property
    def name(self) -> str:
        try:
            return json.loads(self.config_path.read_text()).get("name", self.path.parent.name)
        except (OSError, ValueError):
            return self.path.parent.name

    # ── log I/O ──────────────────────────────────────────────────────────────
    def messages(self) -> Iterator[Message]:
        if not self.log_path.exists():
            return iter(())
        with self.log_path.open("r", encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        return (Message.from_json(ln) for ln in lines)

    def _next_id(self) -> str:
        n = sum(1 for _ in self.messages()) + 1
        return f"m{n}"

    def append(self, msg: Message) -> Message:
        # Advisory lock so two agents appending at once never interleave lines.
        with self.log_path.open("a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                if not msg.id:
                    msg.id = self._next_id()
                f.write(msg.to_json() + "\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        if msg.type in {"claim", "retract", "user_fact", "lock", "unlock", "status"}:
            self.render_head()
        return msg

    # ── posting ──────────────────────────────────────────────────────────────
    def post(self, from_: str, to: str, type: str, body: str, *, thread: str = "",
             refs: Iterable[str] = (), confidence: str = "", in_reply_to: str = "",
             ack_required: bool | None = None, meta: dict | None = None) -> Message:
        if type not in TYPES:
            raise BusError(f"unknown type {type!r}; one of {sorted(TYPES)}")
        if not from_:
            raise BusError("sender identity required (ABUS_AGENT or --as)")
        refs = [r for r in refs if r]
        if type == "claim" and not refs:
            raise BusError("a claim needs at least one --ref (file, log line, URL, or 'user said')")
        if type == "claim" and confidence and confidence not in CONFIDENCE:
            raise BusError(f"confidence must be one of {sorted(CONFIDENCE)}")
        if type == "user_fact" and from_ != "user":
            raise BusError("only --as user may post a user_fact")
        if type in {"answer", "retract", "ack"} and not in_reply_to:
            raise BusError(f"{type} needs the id it refers to")
        if in_reply_to and self.get(in_reply_to) is None:
            raise BusError(f"no such message {in_reply_to}")
        if type == "retract":
            target = self.get(in_reply_to)
            if target.type == "user_fact":
                raise BusError("agents cannot retract a user_fact; ask the user to post a new one")
        if ack_required is None:
            ack_required = type in {"ask", "claim", "user_fact"}
        msg = Message(id="", ts=now_iso(), from_=from_, to=to or BROADCAST, type=type,
                      body=body.strip(), thread=thread, refs=list(refs), confidence=confidence,
                      in_reply_to=in_reply_to, ack_required=ack_required, meta=meta or {})
        return self.append(msg)

    def ack(self, by: str, ids: Iterable[str]) -> list[Message]:
        return [self.post(by, BROADCAST, "ack", "", in_reply_to=i, ack_required=False) for i in ids]

    # ── queries ──────────────────────────────────────────────────────────────
    def get(self, id: str) -> Message | None:
        return next((m for m in self.messages() if m.id == id), None)

    def acked_by(self, agent: str) -> set[str]:
        return {m.in_reply_to for m in self.messages() if m.type == "ack" and m.from_ == agent}

    def inbox(self, agent: str, include_broadcast: bool = True) -> list[Message]:
        seen = self.acked_by(agent)
        out = []
        for m in self.messages():
            if m.type == "ack" or m.from_ == agent or m.id in seen:
                continue
            if m.to == agent or (include_broadcast and m.to == BROADCAST):
                out.append(m)
        return out

    def open_asks(self, for_agent: str | None = None, by_agent: str | None = None) -> list[Message]:
        msgs = list(self.messages())
        answered = {m.in_reply_to for m in msgs if m.type == "answer"}
        asks = [m for m in msgs if m.type == "ask" and m.id not in answered]
        if for_agent:
            asks = [m for m in asks if m.to in (for_agent, BROADCAST)]
        if by_agent:
            asks = [m for m in asks if m.from_ == by_agent]
        return asks

    def retracted(self) -> set[str]:
        return {m.in_reply_to for m in self.messages() if m.type == "retract"}

    def facts(self) -> list[Message]:
        gone = self.retracted()
        return [m for m in self.messages() if m.type in {"claim", "user_fact"} and m.id not in gone]

    def locks(self) -> dict[str, Message]:
        held: dict[str, Message] = {}
        for m in self.messages():
            if m.type == "lock":
                held[m.body] = m
            elif m.type == "unlock":
                held.pop(m.body, None)
        return held

    def statuses(self) -> dict[str, Message]:
        latest: dict[str, Message] = {}
        for m in self.messages():
            if m.type == "status":
                latest[m.from_] = m
        return latest

    def thread(self, name: str) -> list[Message]:
        return [m for m in self.messages() if m.thread == name]

    def agents(self) -> list[str]:
        return sorted({m.from_ for m in self.messages()})

    # ── HEAD: derived current truth ──────────────────────────────────────────
    def render_head(self) -> str:
        facts = self.facts()
        asks = self.open_asks()
        locks = self.locks()
        statuses = self.statuses()
        lines = [f"# HEAD — {self.name}", "",
                 f"_Derived from `{LOG}` at {now_iso()}. Do not edit; post to the bus._", ""]
        lines.append("## Facts (claims minus retractions; user facts first)")
        user = [m for m in facts if m.type == "user_fact"]
        agent = [m for m in facts if m.type == "claim"]
        for m in user:
            lines.append(f"- **[user {m.short_ts}]** {m.body}")
        for m in agent:
            conf = f" _{m.confidence}_" if m.confidence else ""
            refs = f" — refs: {', '.join(m.refs)}" if m.refs else ""
            lines.append(f"- [{m.id} {m.from_} {m.short_ts}]{conf} {m.body}{refs}")
        if not facts:
            lines.append("- (none)")
        lines += ["", "## Open asks"]
        for m in asks:
            lines.append(f"- **{m.id}** {m.from_} → {m.to} ({m.short_ts}): {m.body}")
        if not asks:
            lines.append("- (none)")
        lines += ["", "## Locks"]
        for path, m in sorted(locks.items()):
            lines.append(f"- `{path}` — {m.from_} since {m.short_ts}")
        if not locks:
            lines.append("- (none)")
        lines += ["", "## Agent status"]
        for a, m in sorted(statuses.items()):
            lines.append(f"- **{a}** ({m.short_ts}): {m.body}")
        if not statuses:
            lines.append("- (none)")
        text = "\n".join(lines) + "\n"
        (self.path / HEAD).write_text(text, encoding="utf-8")
        return text

    # ── the wire format an agent reads ───────────────────────────────────────
    def render_inject(self, agent: str, msgs: list[Message]) -> str:
        """The block that gets put in front of an agent. Modelled on how Claude
        Code presents cross-session messages: an unmistakable header, one
        compact entry per message, and the exact command to reply."""
        if not msgs:
            return ""
        out = [f"[agentbus] {len(msgs)} new message(s) for {agent} on bus '{self.name}'. "
               f"These are from other agents, not the user. Ack after reading: "
               f"abus ack {' '.join(m.id for m in msgs)}"]
        for m in msgs:
            head = f"--- {m.id} · {m.type} · from {m.from_} · {m.short_ts}"
            if m.thread:
                head += f" · thread {m.thread}"
            if m.in_reply_to:
                head += f" · re {m.in_reply_to}"
            out.append(head)
            if m.body:
                out.append(m.body)
            tail = []
            if m.refs:
                tail.append("refs: " + ", ".join(m.refs))
            if m.confidence:
                tail.append("confidence: " + m.confidence)
            if tail:
                out.append("  " + "   ".join(tail))
            if m.type == "ask":
                out.append(f'  (reply with: abus answer {m.id} "...")')
        return "\n".join(out) + "\n"


def wait_for_new(bus: Bus, agent: str, poll: float = 2.0, timeout: float | None = None) -> list[Message]:
    """Block until the agent's inbox is non-empty (or timeout). Used by `abus watch`."""
    t0 = time.time()
    while True:
        msgs = bus.inbox(agent)
        if msgs:
            return msgs
        if timeout is not None and time.time() - t0 >= timeout:
            return []
        time.sleep(poll)
