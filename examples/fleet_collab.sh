#!/usr/bin/env bash
# Multi-agent fleet walkthrough: codex ↔ claude ↔ muse over a fresh bus.
# Usage: bash examples/fleet_collab.sh [target-dir]
set -euo pipefail

ROOT="${1:-$(mktemp -d /tmp/agentbus-fleet-XXXXXX)}"
mkdir -p "$ROOT"
cd "$ROOT"

if ! command -v abus >/dev/null 2>&1; then
  echo "abus not on PATH — install first:" >&2
  echo '  pip install "git+https://github.com/yanglinfang/agentbus.git"' >&2
  exit 1
fi

echo "== init bus in $ROOT =="
abus init --name fleet-demo >/dev/null
echo "(instructions block: abus instructions — or copy examples/AGENTS.snippet.md)"

echo "== codex: status + claim + ask claude =="
abus --as codex status "owning sensors"
abus --as codex claim "FL force reads 0 under load" \
  --ref "logs/force.jsonl:12" --conf high --thread fleet-demo
ASK=$(abus --as codex ask claude "which part is on the shipping label?" --thread fleet-demo)
echo "ask id: $ASK"

echo "== claude: inbox (ack), answer, claim =="
abus --as claude inbox --ack
abus --as claude answer "$ASK" "motor assembly EN7"
abus --as claude claim "shipping label names EN7" \
  --ref "answer:$ASK" --conf medium --thread fleet-demo

echo "== muse (third agent): join, receive broadcast ask, answer =="
abus --as muse whoami
abus --as muse status "design brief"
ASK2=$(abus --as claude ask muse "can you consolidate the design brief?" --thread fleet-demo)
echo "ask-to-muse id: $ASK2"
abus --as muse inbox --ack
abus --as muse answer "$ASK2" "brief drafted from HEAD claims"
abus --as muse claim "design brief consolidated" \
  --ref "answer:$ASK2" --conf medium --thread fleet-demo

echo "== codex: inbox (ack) + head =="
abus --as codex inbox --ack
abus head

echo "== done. log: $ROOT/.agentbus/log.jsonl =="
