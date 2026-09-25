"""The five tools, declared once, in a provider-neutral shape.

There are five, and there is deliberately no sixth.  **Nothing here can change the
world.**  There is no ``execute``, no ``restart_service``, no ``kill_query``, no
``scale``.  That is not an omission to be filled in later -- it is the security posture,
and it is enforced by the fact that no such function exists to be called.

The strongest version of "the agent cannot run a destructive command" is not a policy
check, a confirmation prompt, or a system prompt that says please don't.  It is that the
capability was never granted.  An injected instruction that says *run scale-down prod*
reaches a model whose entire tool vocabulary is five read-only verbs, and the worst it
can do is call one of them.

``app/llm.py`` translates these into whatever shape the provider wants.
"""

TOOLS = {
    "search_logs": {
        "name": "search_logs",
        "description": (
            "Find log lines matching a case-insensitive substring or regular expression. "
            "Returns the citation key, level, source and text of each match, newest last. "
            "Quarantined lines are returned with their text redacted so you can see that "
            "something was withheld and where."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Substring or regular expression, e.g. 'timeout' or 'lock|deadlock'.",
                },
                "level": {
                    "type": "string",
                    "enum": ["ANY", "INFO", "WARN", "ERROR"],
                    "description": "Restrict to one severity. Default ANY.",
                },
                "limit": {"type": "integer", "description": "Maximum matches, default 10."},
            },
            "required": ["pattern"],
        },
    },
    "get_log": {
        "name": "get_log",
        "description": (
            "Fetch one log line by citation key, with the lines immediately around it for "
            "context. Use this after search_logs when you need to see what led up to a line."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Citation key, e.g. 'log:4'."},
                "context": {
                    "type": "integer",
                    "description": "How many lines either side, default 2, maximum 5.",
                },
            },
            "required": ["key"],
        },
    },
    "read_metrics": {
        "name": "read_metrics",
        "description": (
            "List the recorded metrics with their values, baselines and notes, exactly as "
            "captured. Values are strings and may carry units, approximations or ranges. "
            "Do not do arithmetic on them yourself -- use compare_metric."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_contains": {
                    "type": "string",
                    "description": "Optional filter on the metric name, e.g. 'latency'.",
                }
            },
        },
    },
    "compare_metric": {
        "name": "compare_metric",
        "description": (
            "Compare one metric against its own baseline, handling units correctly. Returns "
            "a ratio and a direction when the two are genuinely comparable, and "
            "comparable=false with a reason when they are not. When comparable is false, "
            "quote value_raw and baseline_raw and draw your conclusion in words. Never "
            "compute a ratio yourself: '12.4s' against '85ms' is 146 times worse, and the "
            "obvious arithmetic gives the opposite answer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact metric name from read_metrics."}
            },
            "required": ["name"],
        },
    },
    "get_runbook": {
        "name": "get_runbook",
        "description": (
            "Fetch one runbook by id with its full body, whether its mitigation is "
            "automatable, its risk level, and the conditions under which it does not apply. "
            "Read the not_when field before proposing it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Runbook id, e.g. 'RB-01'."}
            },
            "required": ["id"],
        },
    },
}


def specs_for(names):
    """The tool declarations for one agent, in the order given."""
    return [TOOLS[n] for n in names if n in TOOLS]
