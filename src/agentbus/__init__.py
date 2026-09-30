"""agentbus — a file-backed message bus for coding agents.

Any agent that can read a file, run a shell command, or speak MCP can use it.
The store is an append-only JSONL log inside the repo, so `git` is the
cross-machine transport and the whole history is reviewable.
"""

__version__ = "0.2.3"
