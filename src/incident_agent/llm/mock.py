"""Mock mode: replay a recorded reply per agent instead of calling a model.

Replies live in the scenario's ``fixtures/<agent>.json`` and are consumed in order; the
last one repeats. A reply may carry ``tool_uses``, and the loop then calls the real tool
implementations against the real evidence -- so mock mode exercises the tool plumbing for
free, and only the model is replaced.
"""

import json

from incident_agent import config

_fixture_cache = {}
_counters = {}


def _load_fixture(agent):
    if agent not in _fixture_cache:
        path = config.FIXTURES_DIR / f"{agent}.json"
        try:
            with open(path) as f:
                _fixture_cache[agent] = json.load(f)
        except (OSError, ValueError):
            _fixture_cache[agent] = []
    return _fixture_cache[agent]


def reset():
    """Between runs, so a second run in the same process replays from the top."""
    _counters.clear()


def converse(system, messages, tools, agent):
    """Replay a recorded reply for this agent.

    Replies are consumed in order and the last one repeats.  A fixture may carry
    ``tool_uses``; the loop then calls the real tool implementations against the real
    evidence, so mock mode exercises the tool plumbing for free -- only the model is
    replaced.
    """
    replies = _load_fixture(agent)
    if not replies:
        return {
            "text": json.dumps({"error": f"no fixture for {agent!r}"}),
            "tool_uses": [],
            "stop_reason": "end_turn",
            "usage": {"in": 0, "out": 0, "cache_write": 0, "cache_read": 0},
        }

    n = _counters.get(agent, 0)
    _counters[agent] = n + 1
    reply = replies[min(n, len(replies) - 1)]

    tool_uses = [
        {"id": f"mock_{agent}_{n}_{i}", "name": t["name"], "input": t.get("input", {})}
        for i, t in enumerate(reply.get("tool_uses", []))
    ]
    body = reply.get("text", "")
    if not isinstance(body, str):
        body = json.dumps(body)

    return {
        "text": body,
        "tool_uses": tool_uses,
        "stop_reason": "tool_use" if tool_uses else "end_turn",
        "usage": {"in": 0, "out": 0, "cache_write": 0, "cache_read": 0},
    }
