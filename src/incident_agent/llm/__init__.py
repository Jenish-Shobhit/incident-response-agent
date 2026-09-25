"""One calling convention, three backends behind it.

Everything above this file -- the tool loop, the nodes, the graph -- speaks one shape::

    converse(system, messages, tools) -> {"text", "tool_uses", "stop_reason", "usage"}

and builds messages out of three block types: ``text``, ``tool_use``, ``tool_result``.
That shape is Anthropic's, because it is the simpler of the two, and ``llm/bedrock.py``
translates it on the way out and back.

Why the indirection is worth a package: the part of this system that is genuinely easy to
get wrong is the **tool loop**, not the transport.  Appending the assistant's ``tool_use``
after the ``tool_result`` instead of before it is a hard API error; returning two results
in two separate user messages instead of one is a different hard API error.  Both live in
``agents/loop.py``, both are provider-independent, and both can therefore be proved against
whichever backend is reachable.  Swapping the backend afterwards does not put them back.

``MOCK=1`` is the default for a reason.  Every node in this graph can be developed,
debugged and demonstrated end to end without spending a token, which means a model
outage, an expired credential or an exhausted quota costs a demo rather than the day.
"""

from incident_agent import config
from incident_agent.llm import mock
from incident_agent.llm.blocks import text_block, tool_result_block

__all__ = ["converse", "describe", "reset_mock", "text_block", "tool_result_block"]


def converse(system, messages, tools=None, max_tokens=None, temperature=None, agent="?"):
    """One turn. Returns the neutral reply shape regardless of backend."""
    if config.MOCK:
        return mock.converse(system, messages, tools, agent)
    max_tokens = max_tokens or config.MAX_TOKENS
    if config.PROVIDER == "anthropic":
        from incident_agent.llm import anthropic_api

        return anthropic_api.converse(system, messages, tools, max_tokens, temperature)
    from incident_agent.llm import bedrock

    return bedrock.converse(system, messages, tools, max_tokens, temperature)


def reset_mock():
    """Between runs, so a second run in the same process replays from the top."""
    mock.reset()


def describe():
    """One line for the token meter and /health."""
    if config.MOCK:
        return "mock (fixtures, 0 tokens)"
    if config.PROVIDER == "anthropic":
        return f"anthropic {config.ANTHROPIC_MODEL}"
    from incident_agent.llm import bedrock

    return f"bedrock {bedrock.bedrock_model()} in {config.AWS_REGION}"
