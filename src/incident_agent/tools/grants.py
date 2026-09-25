"""Which agent may call which tool. Seven lines that carry the least-privilege claim.

The important property is *where* this is enforced.  These names are turned into the
``tools`` list sent with each individual API call, so an agent is never told that a tool
it may not use exists.  It is not asked to refrain -- it has no way to refer to the
thing.  A prompt that says "do not call get_runbook" is a request; an API call whose
tool list does not contain ``get_runbook`` is a boundary.

Two grants are worth defending because they look like mistakes:

**The planner has no tools at all.**  It reads the evidence summary it is given and
decides who should look at what.  If it could investigate, it would, and the fan-out
would become decoration -- the planner would answer its own questions in one turn and
the specialists would have nothing to do.  Removing the capability is what forces the
delegation to be real.

**The verifier can read but cannot search.**  It gets ``get_log`` and ``read_metrics``,
so it can check any citation the brief makes, and it does not get ``search_logs``, so it
cannot go looking for new evidence to support a conclusion it has already read.  A
verifier that can hunt for confirmation stops being a check and becomes a second author.
"""

GRANTS = {
    "planner":   [],
    "log":       ["search_logs", "get_log"],
    "metric":    ["read_metrics", "compare_metric"],
    "resolver":  ["get_runbook"],
    "verifier":  ["get_log", "read_metrics"],
}

# Every tool that exists, from the grants themselves. If a tool is never granted to
# anyone it is dead code, and this is what a test asserts against.
GRANTED = sorted({t for tools in GRANTS.values() for t in tools})

# Named so a test can assert the absence rather than trusting a comment.
FORBIDDEN_VERBS = (
    "execute", "run_command", "restart", "kill", "scale", "delete",
    "drop", "apply", "deploy", "rollback", "failover",
)


def tools_for(agent):
    """The tool names this agent may call. Unknown agent means no tools, not all tools."""
    return list(GRANTS.get(agent, []))


def may_call(agent, tool):
    return tool in GRANTS.get(agent, [])
