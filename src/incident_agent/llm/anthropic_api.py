"""The Claude API backend. Reads ANTHROPIC_API_KEY through the SDK's own resolution."""

from incident_agent import config

_client = None


def converse(system, messages, tools, max_tokens, temperature):
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
    if config.PROMPT_CACHE:
        sys_block[0]["cache_control"] = {"type": "ephemeral"}

    kwargs = {
        "model": config.ANTHROPIC_MODEL,
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
        if config.PROMPT_CACHE:
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
