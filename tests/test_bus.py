import json
import subprocess
import sys
from pathlib import Path

import pytest

from agentbus.store import Bus, BusError
from agentbus.cli import main


@pytest.fixture
def bus(tmp_path: Path) -> Bus:
    return Bus.init(tmp_path, "t")


def test_init_creates_log_and_head(tmp_path):
    b = Bus.init(tmp_path)
    assert (tmp_path / ".agentbus" / "log.jsonl").exists()
    assert "HEAD" in (tmp_path / ".agentbus" / "HEAD.md").read_text()
    assert (tmp_path / ".agentbus" / ".gitignore").read_text().strip() == "HEAD.md"
    (tmp_path / "deep" / "er").mkdir(parents=True)
    assert Bus.open(tmp_path / "deep" / "er").path == b.path  # found by walking up, like git


def test_claim_requires_ref(bus):
    with pytest.raises(BusError):
        bus.post("a", "*", "claim", "the sky is green")
    m = bus.post("a", "*", "claim", "FL force is 0", refs=["log.jsonl:12"], confidence="high")
    assert m.id == "m1" and m.refs == ["log.jsonl:12"]


def test_inbox_and_ack(bus):
    bus.post("codex", "claude", "note", "hello")
    bus.post("codex", "*", "note", "everyone")
    bus.post("claude", "codex", "note", "my own message")
    inbox = bus.inbox("claude")
    assert [m.body for m in inbox] == ["hello", "everyone"]
    bus.ack("claude", [m.id for m in inbox])
    assert bus.inbox("claude") == []
    # ack by claude does not hide it from a third agent
    assert [m.body for m in bus.inbox("hermes")] == ["everyone"]


def test_ask_stays_open_until_answered(bus):
    a = bus.post("codex", "claude", "ask", "which part shipped?")
    assert [m.id for m in bus.open_asks(for_agent="claude")] == [a.id]
    with pytest.raises(BusError):
        bus.post("claude", "codex", "answer", "a motor")  # needs in_reply_to
    bus.post("claude", "codex", "answer", "a motor", in_reply_to=a.id)
    assert bus.open_asks() == []


def test_retract_removes_from_head(bus):
    c = bus.post("claude", "*", "claim", "firmware rpy wraps", refs=["sim.log"])
    assert "firmware rpy wraps" in bus.render_head()
    bus.post("codex", "*", "retract", "that log was simulated", in_reply_to=c.id)
    head = bus.render_head()
    assert "firmware rpy wraps" not in head


def test_user_fact_protected(bus):
    with pytest.raises(BusError):
        bus.post("claude", "*", "user_fact", "I did the calibration")
    f = bus.post("user", "*", "user_fact", "I did the calibration")
    with pytest.raises(BusError):
        bus.post("claude", "*", "retract", "nah", in_reply_to=f.id)
    assert "**[user" in bus.render_head()


def test_locks(bus):
    bus.post("codex", "*", "lock", "README.md")
    assert bus.locks()["README.md"].from_ == "codex"
    bus.post("codex", "*", "unlock", "README.md")
    assert bus.locks() == {}


def test_unknown_reply_target(bus):
    with pytest.raises(BusError):
        bus.post("a", "*", "ack", "", in_reply_to="m999")


def test_inject_format(bus):
    a = bus.post("codex", "claude", "ask", "still there?")
    text = bus.render_inject("claude", bus.inbox("claude"))
    assert text.startswith("[agentbus] 1 new message(s) for claude")
    assert "from other agents, not the user" in text
    assert f"abus answer {a.id}" in text
    assert bus.render_inject("claude", []) == ""


def test_ids_are_sequential_and_survive_reopen(tmp_path):
    b = Bus.init(tmp_path)
    b.post("a", "*", "note", "1"); b.post("a", "*", "note", "2")
    assert Bus.open(tmp_path).post("a", "*", "note", "3").id == "m3"


def test_cli_roundtrip(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--name", "demo"]) == 0
    capsys.readouterr()
    monkeypatch.setenv("ABUS_AGENT", "codex")
    assert main(["ask", "claude", "what is the interface?"]) == 0
    ask_id = capsys.readouterr().out.strip()
    monkeypatch.setenv("ABUS_AGENT", "claude")
    assert main(["inbox", "--format", "inject", "--ack"]) == 0
    out = capsys.readouterr().out
    assert "[agentbus] 1 new message(s) for claude" in out and ask_id in out
    assert main(["answer", ask_id, "en7"]) == 0
    assert main(["asks", "--all"]) == 0
    assert "(no open asks)" in capsys.readouterr().out

def test_cli_claim_without_ref_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); main(["init"])
    with pytest.raises(SystemExit):
        main(["--as", "a", "claim", "unsourced"])  # --ref is required by argparse


def test_cli_lock_conflict(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path); main(["init"])
    assert main(["--as", "codex", "lock", "x.py"]) == 0
    assert main(["--as", "claude", "lock", "x.py"]) == 2
    assert "locked by codex" in capsys.readouterr().err
    assert main(["--as", "claude", "lock", "x.py", "--force"]) == 0


def test_concurrent_appends_do_not_interleave(tmp_path):
    Bus.init(tmp_path)
    code = ("import sys; from agentbus.store import Bus; b=Bus.open(sys.argv[1]);\n"
            "[b.post(sys.argv[2], '*', 'note', 'x'*200) for _ in range(40)]")
    import os
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src")}
    procs = [subprocess.Popen([sys.executable, "-c", code, str(tmp_path), f"p{i}"], env=env) for i in range(4)]
    assert all(p.wait() == 0 for p in procs)
    lines = (tmp_path / ".agentbus" / "log.jsonl").read_text().splitlines()
    assert len(lines) == 160 and all(json.loads(ln)["body"] == "x" * 200 for ln in lines)


def test_head_refreshes_on_ask_and_answer(bus):
    a = bus.post("codex", "claude", "ask", "hook identity?")
    assert a.id in (bus.path / "HEAD.md").read_text()
    bus.post("claude", "codex", "answer", "baked in", in_reply_to=a.id)
    assert a.id not in (bus.path / "HEAD.md").read_text()


def test_hook_install_bakes_identity_and_is_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path); main(["init"])
    assert main(["--as", "claude", "hook", "claude", "--install"]) == 0
    assert main(["--as", "claude", "hook", "claude", "--install"]) == 0
    cfg = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    cmds = [h["command"] for e in cfg["hooks"]["UserPromptSubmit"] for h in e["hooks"]]
    assert cmds == ["abus --as claude inbox --format inject --ack --quiet-empty"]
    # default (no --as) is per-session identity via hook-run
    monkeypatch.delenv("ABUS_AGENT", raising=False)
    assert main(["hook", "claude", "--install"]) == 0
    cfg = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    cmds = [h["command"] for e in cfg["hooks"]["UserPromptSubmit"] for h in e["hooks"]]
    assert cmds == ["abus hook-run claude --ack"]


def test_hook_run_derives_per_session_identity(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.chdir(tmp_path); main(["init"]); monkeypatch.delenv("ABUS_AGENT", raising=False)
    main(["--as", "codex", "ask", "*", "anyone there?"]); capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "abcdef123456", "cwd": str(tmp_path)})))
    assert main(["hook-run", "claude", "--ack"]) == 0
    out = capsys.readouterr().out
    assert "for claude-abcdef on bus" in out and "You are 'claude-abcdef'" in out
    # a second session sees the same broadcast independently (acks are per identity)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "zzzzzz999", "cwd": str(tmp_path)})))
    assert main(["hook-run", "claude"]) == 0
    assert "for claude-zzzzzz" in capsys.readouterr().out


def test_wake_runs_as_worker_identity(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path); main(["init"])
    marker = tmp_path / "woke.txt"
    assert main(["register-wake", "codex", f"sh -c 'echo $ABUS_AGENT > {marker}'"]) == 0
    assert main(["wake", "codex", "--dry-run"]) == 0
    assert main(["wake", "codex", "--wait"]) == 0
    assert marker.read_text().strip() == "codex-worker"
    b = Bus.open(tmp_path)
    assert any(m.from_ == "abus" and "waking codex as codex-worker" in m.body for m in b.messages())


def test_wake_without_registration_is_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path); main(["init"])
    assert main(["wake", "nobody"]) == 2
    assert "no wake command registered" in capsys.readouterr().err


def test_fresh_hook_identity_does_not_replay_history(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.chdir(tmp_path); main(["init"]); monkeypatch.delenv("ABUS_AGENT", raising=False)
    for i in range(5):
        main(["--as", "codex", "send", "*", f"old chatter {i}"])
    main(["--as", "codex", "ask", "*", "still open for everyone"]); capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "fresh01", "cwd": str(tmp_path)})))
    assert main(["hook-run", "claude"]) == 0
    out = capsys.readouterr().out
    assert "old chatter" not in out and "still open for everyone" in out


def test_bind_session_pins_identity(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.chdir(tmp_path); main(["init"]); monkeypatch.delenv("ABUS_AGENT", raising=False)
    assert main(["bind-session", "0970", "claude-vscode"]) == 0
    main(["--as", "codex", "ask", "claude-vscode", "pinned?"]); capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "0970849a-xyz", "cwd": str(tmp_path)})))
    assert main(["hook-run", "claude"]) == 0
    assert "You are 'claude-vscode'" in capsys.readouterr().out


def test_inbox_json_is_silent_when_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path); main(["init"]); capsys.readouterr()
    assert main(["--as", "a", "inbox", "--format", "json"]) == 0
    assert capsys.readouterr().out == ""


def test_cli_inbox_first_contact_starts_from_now(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path); main(["init"])
    for i in range(3):
        main(["--as", "codex", "send", "*", f"old {i}"])
    main(["--as", "codex", "ask", "*", "open for all"]); capsys.readouterr()
    assert main(["--as", "newbie", "inbox"]) == 0
    out = capsys.readouterr().out
    assert "old 0" not in out and "open for all" in out
    assert main(["--as", "newbie2", "inbox", "--all"]) == 0
    assert "old 0" in capsys.readouterr().out


def test_hook_run_identify_prints_even_when_empty(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.chdir(tmp_path); main(["init"]); monkeypatch.delenv("ABUS_AGENT", raising=False); capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "quiet1", "cwd": str(tmp_path)})))
    assert main(["hook-run", "claude", "--identify"]) == 0
    assert "You are 'claude-quiet1'" in capsys.readouterr().out


def test_fleet_collab_two_agents_ask_answer_claim(tmp_path, monkeypatch, capsys):
    """Exit-criteria smoke: two --as identities collaborate on one bus."""
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--name", "fleet"]) == 0
    capsys.readouterr()
    assert main(["--as", "codex", "status", "owning sensors"]) == 0
    assert main(["--as", "codex", "claim", "FL force is 0", "--ref", "log:1", "--conf", "high"]) == 0
    assert main(["--as", "codex", "ask", "claude", "which part shipped?", "--thread", "fleet"]) == 0
    ask_id = [ln for ln in capsys.readouterr().out.strip().splitlines() if ln.startswith("m")][-1]
    assert main(["--as", "claude", "inbox", "--ack"]) == 0
    out = capsys.readouterr().out
    assert ask_id in out and "which part shipped?" in out
    assert main(["--as", "claude", "answer", ask_id, "EN7"]) == 0
    assert main(["--as", "claude", "claim", "label names EN7", "--ref", f"answer:{ask_id}"]) == 0
    capsys.readouterr()
    assert main(["--as", "codex", "inbox", "--ack"]) == 0
    inbox = capsys.readouterr().out
    assert "EN7" in inbox
    assert main(["asks", "--all"]) == 0
    assert "(no open asks)" in capsys.readouterr().out
    assert main(["head"]) == 0
    head = capsys.readouterr().out
    assert "FL force is 0" in head and "label names EN7" in head
    assert main(["instructions"]) == 0
    assert "abus --as <me> inbox --ack" in capsys.readouterr().out


def test_fleet_collab_three_agents_with_muse(tmp_path, monkeypatch, capsys):
    """Third-agent join: muse receives an ask from claude and answers on the same bus."""
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--name", "fleet3"]) == 0
    capsys.readouterr()
    assert main(["--as", "muse", "whoami"]) == 0
    assert "muse" in capsys.readouterr().out
    assert main(["--as", "muse", "status", "joined"]) == 0
    assert main(["--as", "claude", "ask", "muse", "consolidate the brief?", "--thread", "fleet3"]) == 0
    ask_id = [ln for ln in capsys.readouterr().out.strip().splitlines() if ln.startswith("m")][-1]
    assert main(["--as", "muse", "inbox", "--ack"]) == 0
    inbox = capsys.readouterr().out
    assert ask_id in inbox and "consolidate the brief?" in inbox
    assert main(["--as", "muse", "answer", ask_id, "brief drafted"]) == 0
    assert main(["--as", "muse", "claim", "brief consolidated", "--ref", f"answer:{ask_id}"]) == 0
    capsys.readouterr()
    assert main(["--as", "claude", "inbox", "--ack"]) == 0
    assert "brief drafted" in capsys.readouterr().out
    assert main(["asks", "--all"]) == 0
    assert "(no open asks)" in capsys.readouterr().out
    assert main(["head"]) == 0
    assert "brief consolidated" in capsys.readouterr().out


def test_mcp_example_configs_match_abus_entrypoint():
    """examples/mcp/*.json must use abus --as <name> mcp with distinct identities."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "examples" / "mcp"
    expected = {
        "claude-code.json": "claude",
        "codex.json": "codex",
        "cursor.json": "cursor",
        "muse.json": "muse",
        "generic-bot.json": "bot",
    }
    for name, identity in expected.items():
        cfg = json.loads((root / name).read_text())
        server = cfg["mcpServers"]["agentbus"]
        assert server["command"] == "abus"
        assert server["args"] == ["--as", identity, "mcp"]
    snippet = (root.parent / "AGENTS.snippet.md").read_text()
    assert "abus --as <me> inbox --ack" in snippet
    assert "Agent coordination (agentbus)" in snippet


def test_unregister_wake(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path); main(["init"])
    main(["register-wake", "codex", "true"]); capsys.readouterr()
    assert main(["unregister-wake", "codex"]) == 0
    assert "removed wake command for codex" in capsys.readouterr().out
    assert main(["wake", "codex"]) == 2  # nothing registered any more
