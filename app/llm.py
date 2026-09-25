"""One calling convention, three backends behind it.

Everything above this file -- the tool loop, the nodes, the graph -- speaks one shape::

    converse(system, messages, tools) -> {"text", "tool_uses", "stop_reason", "usage"}

and builds messages out of three block types: ``text``, ``tool_use``, ``tool_result``.
That shape is Anthropic's, because it is the simpler of the two, and ``_bedrock``
translates it on the way out and back.

Why the indirection is worth one file: the part of this system that is genuinely easy to
get wrong is the **tool loop**, not the transport.  Appending the assistant's ``tool_use``
after the ``tool_result`` instead of before it is a hard API error; returning two results
in two separate user messages instead of one is a different hard API error.  Both live in
``app/agent.py``, both are provider-independent, and both can therefore be proved against
whichever backend is reachable.  Swapping the backend afterwards does not put them back.

``MOCK=1`` is the default for a reason.  Every node in this graph can be developed,
debugged and demonstrated end to end without spending a token, which means a model
outage, an expired credential or an exhausted quota costs a demo rather than the day.
"""

import json
import os
import random
import re

MOCK = os.environ.get("MOCK", "1") not in ("0", "false", "False", "")
PROVIDER = os.environ.get("LLM_PROVIDER", "bedrock").lower()
PROMPT_CACHE = os.environ.get("PROMPT_CACHE", "1") not in ("0", "false", "False", "")
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Preference order, best first. Which of these an account may call depends on its IAM
# policy and region, so the first one that answers wins. If access to a better model is
# granted later, this file starts using it on the next run with no edit and no redeploy.
MODEL_PREFERENCE = [
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",   # inference profile
    "anthropic.claude-haiku-4-5-20251001-v1:0",      # bare id, in case the profile is the issue
    "cohere.command-r-plus-v1:0",                    # built for tool use
    "amazon.nova-lite-v1:0",                         # cheapest fallback
]

SELECTED_PATH = os.environ.get("MODEL_CACHE", "docs/model-selected.txt")


def pick_model(force=False):
    """Return the best model that actually answers, and remember it.

    Tries each candidate in order with a one-token call and keeps the first that works.
    The result is cached to a file, so this costs a few tokens once per machine and
    nothing afterwards -- and the file records what was tried and what was refused.

    ``BEDROCK_MODEL`` in the environment always wins. Nothing here overrides an explicit
    choice; it only removes the need to make one.
    """
    explicit = os.environ.get("BEDROCK_MODEL")
    if explicit:
        return explicit

    if not force and os.path.exists(SELECTED_PATH):
        with open(SELECTED_PATH) as f:
            for line in f:
                if line.startswith("SELECTED "):
                    return line.split(None, 1)[1].strip()

    import boto3

    client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
    log, chosen = [], None
    for candidate in MODEL_PREFERENCE:
        try:
            client.converse(
                modelId=candidate,
                messages=[{"role": "user", "content": [{"text": "ok"}]}],
                inferenceConfig={"maxTokens": 4},
            )
            log.append(f"  works    {candidate}")
            chosen = candidate
            break
        except Exception as exc:
            log.append(f"  {type(exc).__name__:24} {candidate}")

    if chosen is None:
        raise RuntimeError("no permitted model answered:\n" + "\n".join(log))

    try:
        os.makedirs(os.path.dirname(SELECTED_PATH) or ".", exist_ok=True)
        with open(SELECTED_PATH, "w") as f:
            f.write(f"SELECTED {chosen}\n\ntried, in preference order:\n" + "\n".join(log) + "\n")
    except OSError:
        pass

    return chosen


# Resolved lazily -- importing this module must never make a network call, or every
# unit test in mock mode would need credentials.
_model = None


def bedrock_model():
    global _model
    if _model is None:
        _model = pick_model()
    return _model


ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

_client = None


# ─────────────────────────────────────────────────────────────────────────────
# the neutral surface
# ─────────────────────────────────────────────────────────────────────────────

def text_block(s):
    return {"type": "text", "text": s}


def tool_result_block(tool_use_id, payload):
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(payload, default=str),
    }


def converse(system, messages, tools=None, max_tokens=1500, temperature=None, agent="?"):
    """One turn. Returns the neutral reply shape regardless of backend."""
    if MOCK:
        return _mock(system, messages, tools, agent)
    if PROVIDER == "anthropic":
        return _anthropic(system, messages, tools, max_tokens, temperature)
    return _bedrock(system, messages, tools, max_tokens, temperature)


# ─────────────────────────────────────────────────────────────────────────────
# anthropic
# ─────────────────────────────────────────────────────────────────────────────

def _anthropic(system, messages, tools, max_tokens, temperature):
    global _client
    import anthropic

    if _client is None:
        _client = anthropic.Anthropic()

    # The system prompt and the tool schemas are byte-identical on every call inside an
    # agent's loop, and identical again for the next agent of the same kind. Marking them
    # cacheable is the single largest cost lever in this system: at ~1,600 tokens of
    # fixed overhead per call, a run that makes 15 calls would otherwise pay 24,000
    # tokens for text it already sent.
    sys_block = [{"type": "text", "text": system}]
    if PROMPT_CACHE:
        sys_block[0]["cache_control"] = {"type": "ephemeral"}

    kwargs = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "system": sys_block,
        "messages": messages,
    }
    # Newer models reject `temperature` outright rather than ignoring it, so it is only
    # sent when explicitly asked for.
    if temperature is not None:
        kwargs["temperature"] = temperature
    if tools:
        t = [dict(x) for x in tools]
        if PROMPT_CACHE:
            t[-1]["cache_control"] = {"type": "ephemeral"}
        kwargs["tools"] = t

    r = _client.messages.create(**kwargs)

    text = "".join(b.text for b in r.content if b.type == "text")
    tool_uses = [
        {"id": b.id, "name": b.name, "input": b.input} for b in r.content if b.type == "tool_use"
    ]
    u = r.usage
    return {
        "text": text,
        "tool_uses": tool_uses,
        "stop_reason": r.stop_reason,
        "usage": {
            "in": u.input_tokens,
            "out": u.output_tokens,
            "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
        },
        "raw_content": [b.model_dump() for b in r.content],
    }


# ─────────────────────────────────────────────────────────────────────────────
# bedrock -- the default live provider
# ─────────────────────────────────────────────────────────────────────────────

def _to_bedrock_messages(messages):
    """Neutral blocks -> Converse blocks. The three shapes are renamed, not restructured."""
    out = []
    for m in messages:
        content = []
        for b in m["content"] if isinstance(m["content"], list) else [text_block(m["content"])]:
            if b["type"] == "text":
                content.append({"text": b["text"]})
            elif b["type"] == "tool_use":
                content.append(
                    {"toolUse": {"toolUseId": b["id"], "name": b["name"], "input": b["input"]}}
                )
            elif b["type"] == "tool_result":
                payload = b["content"]
                try:
                    payload = json.loads(payload) if isinstance(payload, str) else payload
                except ValueError:
                    payload = {"text": str(payload)}
                content.append(
                    {"toolResult": {"toolUseId": b["tool_use_id"], "content": [{"json": payload}]}}
                )
        out.append({"role": m["role"], "content": content})
    return out


def _to_bedrock_tools(tools):
    specs = [
        {
            "toolSpec": {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": {"json": t["input_schema"]},
            }
        }
        for t in tools
    ]
    if PROMPT_CACHE:
        specs.append({"cachePoint": {"type": "default"}})
    return {"tools": specs}


def _bedrock(system, messages, tools, max_tokens, temperature):
    global _client
    import boto3

    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)

    cfg = {"maxTokens": max_tokens}
    if temperature is not None:
        cfg["temperature"] = temperature

    sys_block = [{"text": system}]
    if PROMPT_CACHE:
        sys_block.append({"cachePoint": {"type": "default"}})

    kwargs = {
        "modelId": bedrock_model(),
        "messages": _to_bedrock_messages(messages),
        "system": sys_block,
        "inferenceConfig": cfg,
    }
    if tools:
        kwargs["toolConfig"] = _to_bedrock_tools(tools)

    try:
        r = _client.converse(**kwargs)
    except Exception as exc:
        # Not every Bedrock model supports cache points. Losing the cache is a cost
        # problem; failing the run is a correctness problem. Retry once without them.
        if not PROMPT_CACHE or "cachePoint" not in str(exc) and "cache" not in str(exc).lower():
            raise
        kwargs["system"] = [{"text": system}]
        if tools:
            kwargs["toolConfig"] = {"tools": _to_bedrock_tools(tools)["tools"]}
        r = _client.converse(**kwargs)

    blocks = r["output"]["message"]["content"]
    text = "".join(b["text"] for b in blocks if "text" in b)
    tool_uses = [
        {"id": b["toolUse"]["toolUseId"], "name": b["toolUse"]["name"], "input": b["toolUse"]["input"]}
        for b in blocks
        if "toolUse" in b
    ]
    return {
        "text": text,
        "tool_uses": tool_uses,
        "stop_reason": r.get("stopReason", ""),
        "usage": {
            "in": r["usage"]["inputTokens"],
            "out": r["usage"]["outputTokens"],
            "cache_write": r["usage"].get("cacheWriteInputTokens", 0) or 0,
            "cache_read": r["usage"].get("cacheReadInputTokens", 0) or 0,
        },
        "raw_content": blocks,
    }


# ─────────────────────────────────────────────────────────────────────────────
# mock -- the default, and the reason the graph can be built before a live call
# ─────────────────────────────────────────────────────────────────────────────

FIXTURES = os.environ.get("FIXTURES", "fixtures")
_fixture_cache = {}
_counters = {}


def _load_fixture(agent):
    if agent not in _fixture_cache:
        path = os.path.join(FIXTURES, f"{agent}.json")
        try:
            with open(path) as f:
                _fixture_cache[agent] = json.load(f)
        except (OSError, ValueError):
            _fixture_cache[agent] = []
    return _fixture_cache[agent]


def reset_mock():
    """Between runs, so a second run in the same process replays from the top."""
    _counters.clear()


def _mock(system, messages, tools, agent):
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


def describe():
    """One line for the token ledger and the rationale document."""
    if MOCK:
        return "mock (fixtures, 0 tokens)"
    if PROVIDER == "anthropic":
        return f"anthropic {ANTHROPIC_MODEL}"
    return f"bedrock {bedrock_model()} in {BEDROCK_REGION}"
