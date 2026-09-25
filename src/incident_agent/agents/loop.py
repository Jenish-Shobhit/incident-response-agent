"""The tool loop. Every agent in this system is one call to ``run_agent``.

Two rules in here are not style, they are hard API contracts, and getting either wrong
is a ``ValidationException`` on the first live call rather than a wrong answer you could
notice later:

**1. The assistant message carrying ``tool_use`` is appended before the user message
carrying ``tool_result``.**  The transcript is a conversation: the model said "call this",
then the caller said "here is what it returned".  Appending the result first produces a
``tool_result`` referring to a ``tool_use_id`` that does not appear anywhere earlier in
the transcript, and the API rejects the whole request.

**2. If the model asks for three tools in one turn, all three results go back in ONE user
message.**  Not three messages.  Every ``tool_use`` block in an assistant turn must be
answered in the single user turn that follows it, or the transcript is malformed.

The third rule is a budget one: ``max_rounds`` is a hard stop.  A model that keeps
calling ``search_logs`` with slightly different patterns will do so until something stops
it, and every one of those calls is billed.
"""

import json
import re

from incident_agent.llm import converse, text_block, tool_result_block
from incident_agent.tools.grants import tools_for
from incident_agent.tools.impl import run_tool
from incident_agent.tools.specs import specs_for

JSON_FENCE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)


def extract_json(text):
    """Get the object out of a reply that may be fenced, prefixed, or bare.

    Models are asked for JSON and mostly comply, but "Here is the analysis:" in front of
    it is common and costs nothing to tolerate.  Returns ``None`` rather than raising --
    the caller decides whether a missing object is fatal, and for some agents it is not.
    """
    if not text:
        return None

    fenced = JSON_FENCE.search(text)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text.strip())

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for c in candidates:
        try:
            parsed = json.loads(c)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            continue
    return None


def run_agent(agent, system, user_text, records, max_rounds=3, on_event=None, max_tokens=None):
    """Run one agent to completion and return what it produced.

    ``records`` is the **agent view** -- redacted.  It is passed straight through to the
    tool implementations, which is the mechanism that makes quarantined text unreachable
    rather than merely discouraged.

    Returns ``{"json", "text", "calls", "usage", "rounds"}``.
    """
    allowed = tools_for(agent)
    tools = specs_for(allowed)
    messages = [{"role": "user", "content": [text_block(user_text)]}]

    calls = []
    usage = {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
    rounds = 0

    while rounds < max_rounds:
        rounds += 1
        reply = converse(system, messages, tools=tools, agent=agent, max_tokens=max_tokens)
        for k in usage:
            usage[k] += reply["usage"].get(k if k in ("in", "out") else k, 0)

        if not reply["tool_uses"]:
            return {
                "json": extract_json(reply["text"]),
                "text": reply["text"],
                "calls": calls,
                "usage": usage,
                "rounds": rounds,
            }

        # RULE 1 -- the assistant's own turn goes in first, exactly as it came back.
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": t["id"], "name": t["name"], "input": t["input"]}
                    for t in reply["tool_uses"]
                ]
                + ([text_block(reply["text"])] if reply["text"].strip() else []),
            }
        )

        # RULE 2 -- every result from this turn in one user message.
        result_blocks = []
        for t in reply["tool_uses"]:
            out = run_tool(t["name"], t["input"], records, allowed)
            calls.append({"agent": agent, "tool": t["name"], "input": t["input"], "output": out})
            if on_event:
                on_event({"e": "act", "agent": agent, "tool": t["name"], "input": t["input"]})
            result_blocks.append(tool_result_block(t["id"], out))

        messages.append({"role": "user", "content": result_blocks})

    # Out of rounds with the model still asking for tools. Ask once for the conclusion
    # it already has, with no tools offered, so the turn cannot recurse.
    messages.append(
        {
            "role": "user",
            "content": [
                text_block(
                    "You have used your tool budget. Answer now, in the required JSON "
                    "shape, using only what you have already gathered. Do not request "
                    "any further tools."
                )
            ],
        }
    )
    final = converse(system, messages, tools=None, agent=agent, max_tokens=max_tokens)
    for k in usage:
        usage[k] += final["usage"].get(k, 0)

    return {
        "json": extract_json(final["text"]),
        "text": final["text"],
        "calls": calls,
        "usage": usage,
        "rounds": rounds,
        "truncated": True,
    }
