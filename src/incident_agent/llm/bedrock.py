"""The Amazon Bedrock backend, through the Converse API.

Converse has its own block names (``toolUse``, ``toolResult``, ``cachePoint``); the
functions here rename the neutral blocks on the way out and back, and nothing else in the
system knows Bedrock exists. Credentials come from the standard AWS chain -- a profile, an
SSO session, or an attached role -- never from this repository.
"""

import json

from incident_agent import config
from incident_agent.llm.blocks import text_block

_client = None

# Preference order, best first. Which of these an account may call depends on its IAM
# policy and region, so the first one that answers wins. If access to a better model is
# granted later, this file starts using it on the next run with no edit and no redeploy.
MODEL_PREFERENCE = [
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",   # inference profile
    "anthropic.claude-haiku-4-5-20251001-v1:0",      # bare id, in case the profile is the issue
    "cohere.command-r-plus-v1:0",                    # built for tool use
    "amazon.nova-lite-v1:0",                         # cheapest fallback
]



def pick_model(force=False):
    """Return the best model that actually answers, and remember it.

    Tries each candidate in order with a one-token call and keeps the first that works.
    The result is cached to a file, so this costs a few tokens once per machine and
    nothing afterwards -- and the file records what was tried and what was refused.

    ``BEDROCK_MODEL`` in the environment always wins. Nothing here overrides an explicit
    choice; it only removes the need to make one.
    """
    if config.BEDROCK_MODEL:
        return config.BEDROCK_MODEL

    if not force and config.MODEL_CACHE_PATH.exists():
        with open(config.MODEL_CACHE_PATH) as f:
            for line in f:
                if line.startswith("SELECTED "):
                    return line.split(None, 1)[1].strip()

    import boto3

    client = boto3.client("bedrock-runtime", region_name=config.AWS_REGION)
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
        config.MODEL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(config.MODEL_CACHE_PATH, "w") as f:
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
    if config.PROMPT_CACHE:
        specs.append({"cachePoint": {"type": "default"}})
    return {"tools": specs}


def converse(system, messages, tools, max_tokens, temperature):
    global _client
    import boto3

    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=config.AWS_REGION)

    cfg = {"maxTokens": max_tokens}
    if temperature is not None:
        cfg["temperature"] = temperature

    sys_block = [{"text": system}]
    if config.PROMPT_CACHE:
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
        if not config.PROMPT_CACHE or "cachePoint" not in str(exc) and "cache" not in str(exc).lower():
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
    }
