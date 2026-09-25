"""What the five tools actually do, and the one function that dispatches them.

Every tool reads from the **agent view** -- the redacted one.  That is not a convention
maintained by remembering; ``run_tool`` is handed the agent records and has no reference
to the raw ones.  A tool physically cannot return quarantined text to a model, because
the raw text was never passed into this module.

Redacted lines are still *listed* by ``search_logs`` when they match.  Hiding them
entirely would be worse: the investigator would see log 9 followed by log 11 and have no
way to know that something had been removed.  Showing the key with the text withheld
tells it the truth -- there was a line here, it was quarantined, and you may not read it.
"""

import json
import os
import re

from app.metrics import compare_metric

OVERLAY_PATH = os.environ.get("RUNBOOK_OVERLAY", "data/runbooks.json")

_overlay_cache = None


def overlay():
    """The risk overlay, loaded once. Missing file is survivable -- the runbook body remains."""
    global _overlay_cache
    if _overlay_cache is None:
        try:
            with open(OVERLAY_PATH) as f:
                _overlay_cache = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
        except (OSError, ValueError):
            _overlay_cache = {}
    return _overlay_cache


def _logs(records):
    return [r for r in records if r.get("kind") == "log"]


def search_logs(records, pattern="", level="ANY", limit=10):
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        rx = re.compile(re.escape(pattern), re.I)

    hits = []
    for rec in _logs(records):
        if level and level != "ANY" and rec.get("level") != level:
            continue
        if rx.search(rec.get("text", "")) or rx.search(rec.get("source", "")):
            hits.append(
                {
                    "key": rec["key"],
                    "ts": rec.get("ts", ""),
                    "level": rec.get("level", ""),
                    "source": rec.get("source", ""),
                    "text": rec.get("text", ""),
                    "quarantined": bool(rec.get("quarantined")),
                }
            )

    return {
        "pattern": pattern,
        "matched": len(hits),
        "results": hits[: max(1, min(int(limit or 8), 12))],
    }


def get_log(records, key="", context=2):
    logs = _logs(records)
    idx = next((i for i, r in enumerate(logs) if r["key"] == key), None)
    if idx is None:
        return {"error": f"no log with key {key!r}", "available": [r["key"] for r in logs][:13]}

    span = max(0, min(int(context or 2), 3))
    window = logs[max(0, idx - span) : idx + span + 1]
    return {
        "key": key,
        "line": {
            "key": logs[idx]["key"],
            "ts": logs[idx].get("ts", ""),
            "level": logs[idx].get("level", ""),
            "source": logs[idx].get("source", ""),
            "text": logs[idx].get("text", ""),
            "quarantined": bool(logs[idx].get("quarantined")),
        },
        "context": [
            {
                "key": r["key"],
                "level": r.get("level", ""),
                "source": r.get("source", ""),
                "text": r.get("text", ""),
                "quarantined": bool(r.get("quarantined")),
            }
            for r in window
        ],
    }


def read_metrics(records, name_contains=""):
    out = []
    for rec in records:
        if rec.get("kind") != "metric":
            continue
        if name_contains and name_contains.lower() not in rec["name"].lower():
            continue
        out.append(
            {
                "key": rec["key"],
                "name": rec["name"],
                "value": rec.get("value", ""),
                "baseline": rec.get("baseline", ""),
                "note": rec.get("note", ""),
            }
        )
    return {
        "count": len(out),
        "metrics": out,
        "reminder": "values are strings and may carry units. use compare_metric, do not "
        "do the arithmetic yourself.",
    }


def compare_metric_tool(records, name=""):
    rec = next(
        (r for r in records if r.get("kind") == "metric" and r.get("name") == name), None
    )
    if rec is None:
        names = [r["name"] for r in records if r.get("kind") == "metric"]
        return {"error": f"no metric named {name!r}", "available": names}
    return compare_metric(rec.get("value", ""), rec.get("baseline", ""), name, rec.get("note", ""))


def get_runbook(records, id=""):
    rec = next(
        (r for r in records if r.get("kind") == "runbook" and r.get("id") == id), None
    )
    if rec is None:
        ids = [r["id"] for r in records if r.get("kind") == "runbook"]
        return {"error": f"no runbook with id {id!r}", "available": ids}

    ov = overlay().get(id, {})
    return {
        "key": rec["key"],
        "id": rec["id"],
        "title": rec.get("title", ""),
        "body": rec.get("body", ""),
        "automatable_mitigation": rec.get("automatable_mitigation", False),
        "risk": ov.get("risk", "destructive"),
        "actions": ov.get("actions", []),
        "not_when": ov.get("not_when", []),
        "human_follow_up": ov.get("human_follow_up", []),
        "escalate_because": ov.get("escalate_because", ""),
    }


DISPATCH = {
    "search_logs": search_logs,
    "get_log": get_log,
    "read_metrics": read_metrics,
    "compare_metric": compare_metric_tool,
    "get_runbook": get_runbook,
}


def run_tool(name, args, records, allowed):
    """Execute one tool call. ``allowed`` is this agent's grant list.

    A call to a tool the agent was not granted returns an error *to the model* rather
    than raising.  In practice it cannot happen -- an ungranted tool is not in the list
    sent with the request, so there is nothing to call -- but if a provider ever echoes
    back a name we did not offer, refusing in-band is better than a stack trace.
    """
    if name not in allowed:
        return {"error": f"{name} is not available to this agent", "available": list(allowed)}
    fn = DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool {name!r}", "available": list(allowed)}
    try:
        return fn(records, **(args or {}))
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
